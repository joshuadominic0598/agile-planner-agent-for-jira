"""Observed assignee work and explicitly supplied developer/work-area labels."""
from collections import defaultdict
from . import analytics


def validate(profiles, issues, existing=None):
    available = {(i['project_key'], i['assignee']) for i in issues if i['assignee']}
    if not isinstance(profiles, list):
        raise ValueError('Provide a list of people to configure.')
    cleaned, seen = [], set()
    for p in profiles:
        if not isinstance(p, dict) or not isinstance(p.get('project'), str) or not isinstance(p.get('assignee'), str):
            raise ValueError('Every profile needs a project and assignee.')
        key = (p['project'], p['assignee'])
        if key not in available or key in seen:
            raise ValueError('Choose each existing project assignee at most once.')
        seen.add(key)
        areas = p.get('work_areas', [])
        if not isinstance(areas, list) or len(areas) > 8 or any(not isinstance(a, str) or not a.strip() or len(a.strip()) > 80 for a in areas):
            raise ValueError('Use up to eight nonempty work-area labels per person, each at most 80 characters.')
        if not isinstance(p.get('is_developer'), bool):
            raise ValueError('The developer flag must be true or false.')
        active = p.get('is_active', (existing or {}).get(key, {}).get('is_active', True))
        if not isinstance(active, bool):
            raise ValueError('Membership must be active or inactive.')
        cleaned.append({'is_active': active, 'project': key[0], 'assignee': key[1], 'work_areas': list(dict.fromkeys(a.strip() for a in areas)), 'is_developer': p['is_developer']})
    return cleaned


def dashboard(issues, profiles, sprint=None):
    all_people, selected = defaultdict(list), defaultdict(list)
    for i in issues:
        if i['assignee']:
            all_people[(i['project_key'], i['assignee'])].append(i)
    for i in analytics.select(issues, sprint):
        if i['assignee']:
            selected[(i['project_key'], i['assignee'])].append(i)
    rows, areas, selected_areas = [], defaultdict(set), defaultdict(set)
    developers, active_names = set(), set()
    for key, work in all_people.items():
        p = {'work_areas': [], 'is_developer': False, 'is_active': True, **profiles.get(key, {})}
        if p['is_active']:
            active_names.add(key[1])
            if p['is_developer']:
                developers.add(key[1])
        for area in p['work_areas']:
            areas[area].add(key[1])
        scoped = selected.get(key, [])
        if scoped:
            for area in p['work_areas']:
                selected_areas[area].add(key[1])
        rows.append({'project': key[0], 'assignee': key[1], **p, 'total': len(work), 'selected_total': len(scoped), 'types': analytics.split(work, 'type'), 'selected_types': analytics.split(scoped, 'type')})
    names = {key[1] for key in all_people}
    return {'assigned_people': len(names), 'other_member_count': len(active_names - developers), 'inactive_member_count': len(names - active_names), 'active_people': len(active_names), 'selected_people': len({key[1] for key in selected}), 'selected_work_areas': [{'name': name, 'count': len(names)} for name, names in sorted(selected_areas.items())], 'selected_role_people': len(set().union(*selected_areas.values())), 'developer_count': len(developers), 'unassigned_issues': sum(not i['assignee'] for i in issues), 'work_areas': [{'name': name, 'count': len(names)} for name, names in sorted(areas.items())], 'people': sorted(rows, key=lambda p: (-p['total'], p['assignee'], p['project']))}
