"""Recognize explicit Jira headers without guessing meanings for custom fields."""
import math
import re


def header_key(name):
    return re.sub(r'\s+', ' ', name.strip().replace('_', ' ')).casefold()


ALIASES = {
    'key': ['Issue key', 'Work item key', 'Key'],
    'issue_id': ['Issue id', 'Work item id'],
    'summary': ['Summary', 'Title'],
    'status': ['Status', 'Workflow status'],
    'type': ['Issue Type', 'Work Type', 'Work item type'],
    'project_key': ['Project key'], 'project_name': ['Project name'],
    'category': ['Status Category'], 'priority': ['Priority'],
    'assignee': ['Assignee'], 'reporter': ['Reporter'],
    'description': ['Description'], 'created': ['Created'],
    'comments': ['Comment', 'Comments', 'Custom field (Comment)', 'Custom field (Comments)'],
    'updated': ['Updated'], 'resolved': ['Resolved'],
    'resolution': ['Resolution'],
    'points': ['Custom field (Story point estimate)', 'Custom field (Story Points)', 'Story point estimate', 'Story Points'],
    'original_seconds': ['Original estimate', 'Original estimate (seconds)', 'Time original estimate'],
    'remaining_seconds': ['Remaining Estimate', 'Remaining Estimate (seconds)'],
    'spent_seconds': ['Time Spent', 'Time Spent (seconds)'],
    'sprints': ['Sprint', 'Custom field (Sprint)'],
    'parent_key': ['Parent key'], 'parent_id': ['Parent', 'Parent id'],
    'parent_summary': ['Parent summary'], 'epic_key': ['Epic Link', 'Custom field (Epic Link)'],
}


def matching_fields(fields, role):
    aliases = {header_key(a) for a in ALIASES[role]}
    return [name for name in fields if header_key(name) in aliases]


def values(fields, role):
    return list(dict.fromkeys(v.strip() for name in matching_fields(fields, role) for v in fields[name] if v.strip()))


def number(fields, role):
    raw = values(fields, role)
    if not raw:
        return None, False
    try:
        numbers = {float(v) for v in raw}
        if len(numbers) != 1 or not all(math.isfinite(n) and n >= 0 for n in numbers):
            return None, True
        return numbers.pop(), False
    except ValueError:
        return None, True


def enrich(issue, fields):
    """Also used to backfill old snapshots without changing their raw fields."""
    invalid = []
    for role in ('points', 'original_seconds', 'remaining_seconds', 'spent_seconds'):
        issue[role], bad = number(fields, role)
        if bad:
            invalid.append(role)
    resolutions = values(fields, 'resolution')
    issue['resolution'] = resolutions[0] if len(resolutions) == 1 else ''
    for role in ('issue_id', 'parent_key', 'parent_id', 'parent_summary', 'epic_key'):
        found = values(fields, role)
        issue[role] = found[0] if len(found) == 1 else ''
    issue['normalization_version'] = 4
    return invalid
