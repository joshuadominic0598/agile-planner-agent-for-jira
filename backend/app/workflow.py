"""User-defined status labels, order and colors, scoped to each imported project."""
import hashlib
import re
from collections import Counter, defaultdict

PALETTE = ['#548e82', '#dc7857', '#788db6', '#b68b43', '#9774b4', '#648ca0', '#859651']


def stage_id(label):
    return hashlib.sha256(label.encode('utf-8')).hexdigest()


def default_color(label):
    return PALETTE[int(stage_id(label)[:8], 16) % len(PALETTE)]


def validate(config, statuses):
    assignments = config.get('assignments')
    if not isinstance(assignments, dict) or set(assignments) != set(statuses):
        raise ValueError('Name every discovered status exactly once; unknown statuses are not allowed.')
    cleaned = {}
    for status, label in assignments.items():
        if not isinstance(label, str) or not label.strip():
            raise ValueError('Every status needs a nonempty stage name.')
        label = label.strip()
        if len(label) > 120 and label != status:
            raise ValueError('Custom stage names must be at most 120 characters.')
        cleaned[status] = label
    order = config.get('order', list(cleaned))
    if not isinstance(order, list) or any(not isinstance(s, str) for s in order) or len(order) != len(statuses) or set(order) != set(statuses):
        raise ValueError('Status order must include every discovered status exactly once.')
    colors = config.get('colors', {s: default_color(label) for s, label in cleaned.items()})
    if not isinstance(colors, dict) or set(colors) != set(statuses) or any(not isinstance(c, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in colors.values()):
        raise ValueError('Choose a valid six-digit hex color for every status.')
    group_colors = {}
    for status in order:
        color = colors[status].lower()
        group_colors.setdefault(cleaned[status], color)
    return {'version': 3, 'assignments': cleaned, 'order': order, 'colors': {s: group_colors[cleaned[s]] for s in order}}


def describe(issues, saved=None):
    counts = Counter(i['status'] for i in issues)
    categories = defaultdict(set)
    for issue in issues:
        categories[issue['status']].add(issue['category'])
    assignments = {status: status for status in counts}
    if saved:
        if saved.get('version', 1) >= 2:
            assignments.update({s: label for s, label in saved['assignments'].items() if s in counts})
        else:
            labels = {g['id']: g['label'] for g in saved['groups']}
            assignments.update({s: labels[g] for s, g in saved['assignments'].items() if s in counts})
    default_order = [s for s, _ in counts.most_common()]
    order = [s for s in (saved or {}).get('order', default_order) if s in counts]
    order += [s for s in default_order if s not in order]
    colors = {s: (saved or {}).get('colors', {}).get(s, default_color(assignments[s])) for s in order}
    groups = {}
    for status in order:
        label = assignments[status]
        groups.setdefault(label, {'id': stage_id(label), 'label': label, 'color': colors[status]})
    return {
        'version': 3, 'assignments': assignments, 'order': order, 'colors': colors,
        'groups': list(groups.values()),
        'configured': saved is not None,
        'customized': any(status != label for status, label in assignments.items()) or order != default_order or any(colors[s] != default_color(assignments[s]) for s in order),
        'statuses': [{'name': s, 'count': counts[s], 'jira_categories': sorted(categories[s])} for s in order],
    }


def resolve(issues, saved=None):
    projects = defaultdict(list)
    for issue in issues:
        projects[issue['project_key']].append(issue)
    return {key: describe(rows, (saved or {}).get(key)) for key, rows in projects.items()}


def group(issue, configs):
    label = configs[issue['project_key']]['assignments'][issue['status']]
    return {'id': stage_id(label), 'label': label}


def stage_counts(issues, configs):
    groups = {}
    members = defaultdict(set)
    for config in configs.values():
        for g in config['groups']:
            groups.setdefault(g['id'], g)
        for status, label in config['assignments'].items():
            members[stage_id(label)].add(status)
    counts = Counter(group(i, configs)['id'] for i in issues)
    # Include zero counts and retain the configured order in every sprint.
    return [{**g, 'count': counts[ident], 'statuses': sorted(members[ident])} for ident, g in groups.items()]
