"""Backlog scope, estimates and planning headroom under explicit owner rules."""

import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from . import analytics, planning_people, recency, store


class ResourceCapacity(BaseModel):
    available: bool = True
    unit: Literal['points', 'hours'] = 'points'
    budget: float | None = Field(default=None, ge=0, le=10000)


class PlanningConfig(BaseModel):
    project: str = Field(default='', max_length=100)
    scope: Literal['project', 'sprint'] = 'sprint'
    sprint: str = Field(default='', max_length=200)
    completion: Literal['category', 'statuses'] = 'category'
    finished_statuses: list[str] = Field(default_factory=list, max_length=100)
    focus_priorities: list[str] = Field(default_factory=list, max_length=100)
    unit: Literal['points', 'hours'] = 'points'
    time_field: Literal['remaining_seconds', 'original_seconds'] = 'remaining_seconds'
    budget: float | None = Field(default=None, gt=0, le=10000)
    capacity_unit: Literal['points', 'hours'] | None = None
    capacity_cadence: Literal['per_sprint'] = 'per_sprint'
    resources: dict[str, ResourceCapacity] = Field(default_factory=dict, max_length=500)
    pending_priorities: list[str] = Field(default_factory=list, max_length=100)
    basis: Literal['open', 'all'] = 'all'
    parent_policy: Literal['leaf_only', 'all_estimated'] = 'leaf_only'
    roster: Literal['developers', 'configured'] = 'developers'

    @model_validator(mode='after')
    def align_scope(self):
        if self.scope == 'project':
            self.sprint = ''
        return self


def saved(dataset_id, project):
    row = store.mongo().planning_settings.find_one({'dataset_id': dataset_id, 'project': project})
    value = dict(row['config']) if row else PlanningConfig(project=project, scope='project').model_dump()
    value.update(focus_priorities=[], pending_priorities=[])
    notice = ''
    legacy_sprint = value.pop('capacity_sprint', '')
    if value.get('budget') is not None and (legacy_sprint or 'capacity_cadence' not in value):
        value['budget'] = None
        notice = (
            'Capacity is now per person, per sprint. Set a default and any individual overrides, then save.'
        )
    return {**PlanningConfig(**value).model_dump(), **({'notice': notice} if notice else {})}


def save(dataset_id, config):
    report(dataset_id, config)
    value = config.model_dump()
    store.mongo().planning_settings.update_one(
        {'dataset_id': dataset_id, 'project': config.project}, {'$set': {'config': value}}, upsert=True
    )
    return value


def report(dataset_id, config):
    if not config.project:
        raise ValueError(
            'Choose one project for backlog management; point scales can differ between projects.'
        )
    rows = store.summaries(dataset_id, config.project)
    if not rows:
        raise ValueError('Choose a project included in this import.')
    if config.completion == 'statuses' and not config.finished_statuses:
        raise ValueError('Choose at least one status to treat as finished.')
    statuses = {row['status'] for row in rows}
    if set(config.finished_statuses) - statuses:
        raise ValueError('A finished status is not present in this project.')
    names = {name for row in rows for name in row['sprints']}
    if config.scope == 'sprint' and config.sprint not in names:
        raise ValueError('Choose a named sprint for the backlog scope.')

    def finished(row):
        return (
            row['status'] in config.finished_statuses
            if config.completion == 'statuses'
            else row['category'].casefold() == 'done'
        )

    scoped = analytics.select(rows, config.sprint if config.scope == 'sprint' else '')
    backlog = [row for row in scoped if not finished(row)]
    field = 'points' if config.unit == 'points' else config.time_field
    divisor = 1 if config.unit == 'points' else 3600

    def amount(row):
        return row.get(field) / divisor if row.get(field) is not None else None

    by_key = {row['key']: row for row in rows}

    def ancestors(row):
        found = set()
        parent = row.get('parent_key')
        while parent and parent not in found and parent != row['key']:
            found.add(parent)
            parent = by_key.get(parent, {}).get('parent_key')
        return found

    def counted(items, universe=None):
        parents = set().union(*(ancestors(row) for row in (universe if universe is not None else items)))
        return [
            row
            for row in items
            if config.parent_policy != 'leaf_only'
            or not (row['key'] in parents or row.get('is_parent') or row['type'].casefold() == 'epic')
        ]

    estimates = counted(backlog)
    known = sum(amount(row) for row in estimates if amount(row) is not None)
    profiles = {
        name: profile
        for (project, name), profile in store.people_profiles(dataset_id).items()
        if project == config.project
    }
    known_people = {row['assignee'] for row in rows if row['assignee']} | set(profiles)
    if set(config.resources) - known_people:
        raise ValueError('Individual capacity must refer to a project assignee or saved profile.')
    if set(config.pending_priorities) - {row['priority'] for row in rows}:
        raise ValueError('A priority awaiting refinement is not present in this project.')
    workload_rows = scoped if config.scope == 'sprint' else []
    roster = []
    for name in sorted(known_people):
        profile = profiles.get(name, {})
        active = profile.get('is_active', True)
        resource = config.resources.get(name)
        unit = resource.unit if resource else config.capacity_unit or config.unit
        budget = resource.budget if resource else config.budget
        available = resource.available if resource else True

        def person_amount(row):
            value = row.get('points' if unit == 'points' else config.time_field)
            return value / (1 if unit == 'points' else 3600) if value is not None else None

        confirmed = (
            name in profiles
            and active
            and available
            and (config.roster == 'configured' or profile.get('is_developer', False))
        )
        assigned = [row for row in workload_rows if row['assignee'] == name]
        load_rows = counted(
            [row for row in assigned if config.basis == 'all' or not finished(row)],
            [row for row in workload_rows if config.basis == 'all' or not finished(row)],
        )
        missing = sum(person_amount(row) is None for row in load_rows)
        uncertain_category = (
            config.completion == 'category'
            and config.basis == 'open'
            and any(not row.get('category') for row in load_rows)
        )
        estimated_parents = {
            row['key']
            for row in workload_rows
            if person_amount(row) is not None and (config.basis == 'all' or not finished(row))
        }
        overlap = config.parent_policy == 'all_estimated' and any(
            bool(ancestors(row) & estimated_parents) and person_amount(row) is not None
            for row in workload_rows
            if config.basis == 'all' or not finished(row)
        )
        load = round(sum(person_amount(row) for row in load_rows if person_amount(row) is not None), 2)
        reliable = (
            not missing
            and not uncertain_category
            and not overlap
            and not any(row.get('hierarchy_warning') for row in assigned)
        )
        allocation_room = round(budget - load, 2) if budget is not None and confirmed and reliable else None
        headroom = allocation_room if config.scope == 'sprint' else None
        roster.append(
            {
                **planning_people.insights(
                    [row for row in rows if row['assignee'] == name], counted, finished
                ),
                'name': name,
                'active': active,
                'configured': name in profiles,
                'developer': profile.get('is_developer', False),
                'roles': profile.get('work_areas', []),
                'eligible': confirmed,
                'tickets': len(assigned),
                'available': available,
                'unit': unit,
                'known_load': load if config.scope == 'sprint' else None,
                'allocation_room': allocation_room,
                'missing_estimates': missing,
                'estimate_complete': reliable,
                'headroom': headroom,
                'budget': budget,
                'typical_types': analytics.split([row for row in rows if row['assignee'] == name], 'type'),
            }
        )

    counted_keys = {item['key'] for item in estimates}

    def priority_missing(row):
        return not row.get('priority', '').strip() or row['priority'] in config.pending_priorities

    people_by_name = {person['name']: person for person in roster}
    planning_units = {person['unit'] for person in roster if person['eligible']} or {config.unit}

    def brief(row):
        missing = []
        refinement_unit = people_by_name.get(row['assignee'], {}).get('unit', config.unit)
        if not row['assignee']:
            refinement_unit = next(
                (
                    unit
                    for unit in sorted(planning_units)
                    if row.get('points' if unit == 'points' else config.time_field) is not None
                ),
                config.unit,
            )
        estimate_field = 'points' if refinement_unit == 'points' else config.time_field
        if row.get(estimate_field) is None:
            missing.append('estimate')
        if priority_missing(row):
            missing.append('priority')
        if row['key'] not in counted_keys:
            readiness, next_step = (
                'parent_tracking',
                'Review parent scope alongside its children; parent estimate excluded.',
            )
        elif missing and row['assignee']:
            readiness = 'owner_refinement'
            next_step = f'Ask {row["assignee"]} to refine the {" and ".join(missing)} before scheduling.'
        elif missing:
            readiness = 'triage'
            next_step = 'Reanalyse scope, priority and estimate; identify a suitable owner before scheduling.'
        elif not row['assignee']:
            readiness, next_step = (
                'needs_owner',
                'Match a suitable available person using roles and per-sprint capacity.',
            )
        else:
            readiness, next_step = (
                'ready',
                'Ready for a planning discussion; check assignee capacity and dependencies.',
            )
        time = row.get(config.time_field)
        return {
            'readiness': readiness,
            'refinement_unit': refinement_unit,
            'next_step': next_step,
            'refinement_owner': row['assignee'] if readiness == 'owner_refinement' else '',
            'priority_finalized': not priority_missing(row),
            'estimates': {'points': row.get('points'), 'hours': time / 3600 if time is not None else None},
            **{
                key: row.get(key)
                for key in (
                    'key',
                    'summary',
                    'status',
                    'category',
                    'type',
                    'priority',
                    'assignee',
                    'parent_key',
                    'points',
                )
            },
            'estimate': amount(row),
            'estimate_counted': row['key'] in counted_keys,
        }

    ticket_rows = [brief(row) for row in recency.latest(backlog, len(backlog))]
    missing_estimates = sum(amount(row) is None for row in estimates)
    missing_priorities = sum(priority_missing(row) for row in estimates)
    compatible = [p for p in roster if p['eligible'] and p['unit'] == config.unit]
    capacity = round(sum(p['budget'] or 0 for p in compatible), 2)
    complete_capacity = bool(compatible) and all(p['budget'] is not None for p in compatible)
    forecast = {'minimum_sprints': None, 'unit': config.unit, 'capacity_per_sprint': capacity}
    if not estimates:
        forecast['message'] = 'No unfinished counted work in this scope.'
    elif missing_estimates or missing_priorities:
        forecast['message'] = 'Prioritise and estimate the remaining work before forecasting completion.'
    elif not complete_capacity or capacity <= 0:
        forecast['message'] = (
            'Set per-sprint capacity for suitable available people before estimating a planning horizon.'
        )
    elif any(row.get('hierarchy_warning') for row in estimates):
        forecast['message'] = 'Resolve hierarchy warnings before forecasting.'
    elif config.parent_policy == 'all_estimated' and any(ancestors(row) & counted_keys for row in estimates):
        forecast['message'] = 'Resolve overlapping parent and child estimates before forecasting.'
    elif any(not row.get('category') for row in estimates) and config.completion == 'category':
        forecast['message'] = 'Resolve missing Status Category values before forecasting.'
    else:
        forecast['minimum_sprints'] = math.ceil(known / capacity)
        forecast['message'] = (
            'Theoretical minimum sprint budgets, assuming this entire compatible pool can do the work and has no other commitments. Not a delivery date; role fit and dependencies still need review.'
        )
    readiness = [
        {'name': name, 'count': sum(ticket['readiness'] == name for ticket in ticket_rows)}
        for name in ('triage', 'owner_refinement', 'needs_owner', 'ready', 'parent_tracking')
    ]
    result = {
        'readiness': readiness,
        'forecast': forecast,
        'allocation_basis': 'Selected sprint headroom'
        if config.scope == 'sprint'
        else 'One hypothetical sprint; existing sprint commitments not deducted',
        'config': config.model_dump(),
        'scope_label': config.sprint
        if config.scope == 'sprint'
        else (rows[0].get('project_name') or config.project) + ' · whole project',
        'metrics': {
            'scope_tickets': len(scoped),
            'backlog_tickets': len(backlog),
            'finished_tickets': sum(finished(row) for row in scoped),
            'unassigned': sum(not row['assignee'] for row in backlog),
            'focus_priority': sum(row['priority'] in config.focus_priorities for row in backlog),
            'focus_priority_known_estimate': round(
                sum(
                    amount(row)
                    for row in estimates
                    if row['priority'] in config.focus_priorities and amount(row) is not None
                ),
                2,
            ),
            'focus_priority_missing_estimates': sum(
                row['priority'] in config.focus_priorities and amount(row) is None for row in estimates
            ),
            'known_estimate': round(known, 2),
            'estimated_tickets': sum(amount(row) is not None for row in estimates),
            'counted_tickets': len(estimates),
            'missing_estimates': missing_estimates,
            'missing_priorities': missing_priorities,
            'triage': sum(t['readiness'] == 'triage' for t in ticket_rows),
            'owner_refinement': sum(t['readiness'] == 'owner_refinement' for t in ticket_rows),
            'headroom_people': sum(
                person['developer'] and person['headroom'] is not None and person['headroom'] > 0
                for person in roster
            ),
            'active_developers': sum(person['developer'] and person['active'] for person in roster),
            'overloaded_developers': sum(
                person['developer']
                and person['eligible']
                and person['budget'] is not None
                and person['known_load'] is not None
                and person['known_load'] > person['budget']
                for person in roster
            ),
            'unclassified': sum(not row.get('category') for row in scoped),
        },
        'statuses': analytics.split(backlog, 'status'),
        'priorities': analytics.split(backlog, 'priority'),
        'priority_options': analytics.split([row for row in rows if row['priority']], 'priority'),
        'types': analytics.split(backlog, 'type'),
        'people': roster,
        'tickets': ticket_rows,
        'notes': [
            'Capacity is a per-person, per-sprint planning budget. Points and hours are never converted or added together.',
            'Whole-project allocations model one hypothetical sprint with no existing commitments deducted. Selected-sprint allocations deduct its chosen workload only. Neither proves calendar availability.',
            'Assigned tickets missing priority or estimates need assignee-led refinement. Unassigned tickets missing these inputs need triage before scheduling. A populated priority is treated as ready for planning.',
            'Missing estimates are unknown, not zero. Exclude parents/epics removes exported parents and epics from estimate totals; their records remain visible.',
            'Saved roles and membership are owner-provided. Ticket type history is descriptive evidence, not proof of skills.',
            'Status and sprint membership are a snapshot, not historical carryover, velocity or original commitment.',
            'People profiles use all project assignments. Finished points by sprint use current finished status and exported membership, not who completed the work or when. Multi-sprint tickets can appear in several rows; do not add these rows together.',
        ],
    }
    result['fingerprint'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def validate_plan(context, groups, assignments, assessments=None):
    report = context.planning_report
    allowed = set(context.planning_keys)
    if getattr(context, 'planning_assessment_required', False):
        if not isinstance(assessments, dict) or set(assessments) != allowed:
            raise ValueError('Assess every batch ticket exactly once, using its exact key.')
        if any(
            not isinstance(text, str) or not 30 <= len(text.strip()) <= 500 for text in assessments.values()
        ):
            raise ValueError(
                'Each ticket assessment needs a specific finding and next action in 30–500 characters.'
            )
    assigned_keys, seen = set(), set()
    clean_groups = []
    if len(groups) > 12:
        raise ValueError('Use at most twelve work categories per batch.')
    for group in groups:
        name, keys = group.get('name', '').strip(), group.get('keys', [])
        if not name or len(name) > 100 or not keys:
            raise ValueError('Each category needs a short name and ticket keys.')
        if len(set(keys)) != len(keys) or any(key not in allowed or key in seen for key in keys):
            raise ValueError('Categories must partition the current batch without unknown or duplicate keys.')
        seen.update(keys)
        clean_groups.append({'name': name, 'keys': keys})
    if seen != allowed:
        raise ValueError(
            'Include every batch ticket exactly once. Missing keys: ' + ', '.join(sorted(allowed - seen))
        )
    tickets = {ticket['key']: ticket for ticket in report['tickets']}
    people = {
        person['name']: person
        for person in report['people']
        if person['eligible'] and person['allocation_room'] is not None and person['allocation_room'] > 0
    }
    reserved = dict(getattr(context, 'planning_reserved', {}))
    clean_assignments = []
    for item in assignments:
        key, person, reason = item.get('key'), item.get('person'), item.get('reason', '').strip()
        if key not in allowed or key in assigned_keys:
            raise ValueError(f'{key}: use each allowed unassigned ticket at most once.')
        if person not in people:
            raise ValueError(
                f'{key}: {person} is not eligible. Choose an exact name from: ' + ', '.join(people)
            )
        if not reason or len(reason) > 500:
            raise ValueError(f'{key}: give one brief reason between 1 and 500 characters.')
        ticket = tickets[key]
        estimate = ticket['estimates'][people[person]['unit']]
        if (
            ticket['assignee']
            or estimate is None
            or not ticket['estimate_counted']
            or not ticket['priority_finalized']
        ):
            raise ValueError(
                f'{key} cannot be allocated: it is already assigned, unestimated in this person’s unit, awaiting priority refinement or excluded from estimate counting. Allowed assignment keys: '
                + ', '.join(
                    t['key']
                    for t in tickets.values()
                    if t['key'] in allowed
                    and not t['assignee']
                    and t['estimates'][people[person]['unit']] is not None
                    and t['priority_finalized']
                    and t['estimate_counted']
                )
            )
        used = reserved.get(person, 0) + estimate
        if used > people[person]['allocation_room'] + 1e-8:
            raise ValueError('The proposed allocations exceed this person’s planning headroom.')
        reserved[person] = used
        assigned_keys.add(key)
        clean_assignments.append(
            {
                'key': key,
                'person': person,
                'reason': reason,
                'estimate': estimate,
                'unit': people[person]['unit'],
            }
        )
    context.planning_reserved = reserved
    context.planning_plan = {
        'groups': clean_groups,
        'assignments': clean_assignments,
        'assessments': assessments or {},
    }
    return {
        'accepted': True,
        'groups': len(clean_groups),
        'assignments': len(clean_assignments),
        'note': 'Suggestions only. No Jira ticket or assignment was changed.',
    }
