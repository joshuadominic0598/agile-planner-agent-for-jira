"""Direct parent relationships from explicit exported fields; no type-name guessing."""
import re
from collections import Counter
from .references import Index


def decorate(issues):
    index = Index(issues)
    by_key = index.keys
    for issue in issues:
        token = issue.get('parent_key') or issue.get('parent_id') or issue.get('epic_key') or ''
        parent, reason = index.resolve(token, issue['project_key']) if token else (None, '')
        issue['parent_reference'] = token
        issue['parent_key'] = parent['key'] if parent else token if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*-\d+', token) else ''
        issue['parent_title'] = parent['summary'] if parent else issue.get('parent_summary', '')
        issue['parent_reference_problem'] = reason
        issue['hierarchy_warning'] = 'Ambiguous parent reference; multiple tickets match.' if reason == 'ambiguous' else ''
    # Detect cyclic edges without recursively traversing an arbitrarily deep CSV.
    graph = {i['key']: i.get('parent_key') for i in issues}
    done, cyclic = set(), set()
    for key in graph:
        path, position = [], {}
        current = key
        while current in graph and current not in done and current not in position:
            position[current] = len(path)
            path.append(current)
            current = graph[current]
        if current in position:
            cyclic.update(path[position[current]:])
        done.update(path)
    for issue in issues:
        if issue['key'] in cyclic:
            issue['parent_key'] = ''
            issue['hierarchy_warning'] = 'Cyclic parent link excluded; original fields are preserved.'
    counts = Counter(i['parent_key'] for i in issues if i.get('parent_key'))
    for issue in issues:
        issue['child_count'] = counts[issue['key']]
        issue['is_parent'] = issue['child_count'] > 0
        issue['parent_in_export'] = issue.get('parent_key', '').casefold() in by_key
        issue['has_parent'] = bool(issue.get('parent_reference')) and not issue['hierarchy_warning']
    return issues
