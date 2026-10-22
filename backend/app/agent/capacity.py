"""Capacity arithmetic against an explicit user planning assumption."""

from .. import analytics, store


def analyze(context, project, sprint, points_per_developer, basis, parent_policy):
    scope = getattr(context, 'context_scope', {})
    chosen = project or scope.get('project') or context.project
    if chosen in {'__all__', '__current__'}:
        chosen = context.project if chosen == '__current__' else ''
    if not chosen and len(context.projects) == 1:
        chosen = context.projects[0]
    if not chosen:
        return {
            'clarification': 'Which project should I use? Capacity rules and point scales can differ between projects.'
        }
    rows, key = context.scoped(chosen)
    reference = sprint or scope.get('sprint') or context.sprint or context.active_sprint
    if reference in {None, '', '__all__', '__unscheduled__'}:
        return {'clarification': 'Which named sprint should I assess?'}
    resolved = context.resolve_sprint(reference, rows)
    if 'sprint' not in resolved:
        return resolved
    remembered = getattr(context, 'conversation_memory', {}).get('capacity_rule') or {}
    if points_per_developer is None and remembered.get('project') == key:
        points_per_developer = remembered.get('points_per_developer')
        parent_policy = parent_policy or remembered.get('parent_policy')
    if points_per_developer is None:
        return {
            'clarification': 'How does your team define available capacity: a point budget, time budget, or another rule? Supply the budget before comparing people.'
        }
    if type(points_per_developer) not in (int, float) or not 0 < points_per_developer <= 1000:
        raise ValueError('Use an explicit positive story-point budget up to 1000.')
    if basis not in {'committed', 'open'} or parent_policy not in {None, 'all_estimated', 'leaf_only'}:
        raise ValueError('Choose committed/open load and an optional parent estimate policy.')
    selected = analytics.select(rows, resolved['sprint'])
    profiles = {
        name: profile
        for (project_key, name), profile in store.people_profiles(context.dataset_id).items()
        if project_key == key
    }
    names = {i['assignee'] for i in selected if i['assignee']}
    names |= {name for name, p in profiles.items() if p.get('is_developer') and p.get('is_active', True)}
    parents = {i.get('parent_key') for i in selected if i.get('parent_key')}
    estimated = {i['key'] for i in selected if i.get('points') is not None}
    overlap = sorted(
        {i['parent_key'] for i in selected if i.get('parent_key') in estimated and i['key'] in estimated}
    )
    overlap_keys = set(overlap) | {i['key'] for i in selected if i.get('parent_key') in overlap}
    roster = []
    for name in sorted(names):
        profile = profiles.get(name, {})
        if not profile.get('is_active', True):
            continue
        assigned = [
            i
            for i in selected
            if i['assignee'] == name and (parent_policy != 'leaf_only' or i['key'] not in parents)
        ]
        open_work = [i for i in assigned if i.get('category', '').casefold() != 'done']
        counted = assigned if basis == 'committed' else open_work
        points = sum(i['points'] for i in counted if i.get('points') is not None)
        missing = sum(i.get('points') is None for i in counted)
        categories_missing = sum(not i.get('category') for i in assigned)
        reliable = (
            not missing
            and not (parent_policy is None and any(i['key'] in overlap_keys for i in counted))
            and not (basis == 'open' and categories_missing)
        )
        roster.append(
            {
                'name': name,
                'developer_confirmed': profile.get('is_developer', False),
                'role_confirmed': name in profiles,
                'roles': profile.get('work_areas', []),
                'assigned_tickets': len(assigned),
                'open_tickets': len(open_work),
                'committed_points': sum(i['points'] for i in assigned)
                if all(i.get('points') is not None for i in assigned)
                else None,
                'known_committed_points': sum(i['points'] for i in assigned if i.get('points') is not None),
                'known_load_points': points,
                'unestimated_tickets': missing,
                'budget_points': points_per_developer if profile.get('is_developer') else None,
                'headroom_points': round(points_per_developer - points, 2)
                if reliable and profile.get('is_developer')
                else None,
                'estimate_complete': reliable,
            }
        )
    actual = {'project': key, 'sprint': resolved['sprint']}
    if actual not in context.used_scopes:
        context.used_scopes.append(actual)
    context.metrics_used = True
    return {
        'scope': actual,
        'basis': basis,
        'points_per_developer': points_per_developer,
        'assumption_source': 'User-supplied planning rule; not a universal capacity or productivity measure.',
        'basis_note': 'Committed means the currently assigned exported sprint scope, not verified original sprint commitment history.',
        'people': roster[:150],
        'roster_total': len(roster),
        'truncated': len(roster) > 150,
        'estimated_parent_child_overlap': overlap[:30],
        'parent_policy': parent_policy,
        'unassigned_tickets': sum(not i['assignee'] for i in selected),
        'notes': 'All assigned work in the selected sprint is counted, independent of previous person/priority/status filters. Open load excludes only CSV Status Category Done. Unestimated work is unknown, not zero. Only confirmed active developers are developer candidates; other assignees have unconfirmed roles. Zero-assignment people appear only when present in the saved active developer roster. Positive headroom under this assumption does not prove calendar availability, suitable skills, leave, other-project work, or delivery capacity.',
    }
