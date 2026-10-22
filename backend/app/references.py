"""Resolve explicit ticket references without treating ordinary numeric fields as IDs."""
import re
from collections import defaultdict

from .columns import header_key

KEY = re.compile(r'(?<![\w-])[A-Za-z][A-Za-z0-9_]*-\d+(?![\w-])')
LINK_FIELDS = r'issue link|work item link|linked issues?|linked items?|ticket references?|related issues?|related tickets?|blocks|blocked by|subtasks?|sub-tasks?'
NUMBER = re.compile(r'(?<![\w.-])\d+(?![\w.-])')


class Index:
    def __init__(self, issues):
        self.keys = {i['key'].casefold(): i for i in issues}
        self.ids, self.numbers = defaultdict(list), defaultdict(list)
        for issue in issues:
            if issue.get('issue_id'):
                self.ids[issue['issue_id']].append(issue)
            suffix = issue['key'].rsplit('-', 1)[-1]
            if suffix.isdigit():
                self.numbers[(issue['project_key'], str(int(suffix)))].append(issue)

    def resolve(self, token, project):
        if token.casefold() in self.keys:
            return self.keys[token.casefold()], ''
        if not token.isdigit():
            return None, 'not_in_export'
        ids = self.ids.get(token, [])
        numbered = self.numbers.get((project, str(int(token))), [])
        candidates = {i['key']: i for i in [*ids, *numbered]}
        if len(ids) > 1 or len(numbered) > 1 or len(candidates) > 1:
            return None, 'ambiguous'
        if candidates:
            return next(iter(candidates.values())), ''
        return None, 'not_in_export'


def reference_field(name):
    name = header_key(name)
    return (name in ('issue id', 'work item id') or bool(re.search(r'\b(parent|epic link|epic key|issue link|work item link|linked issues?|linked items?|ticket references?|related issues?|related tickets?|blocks|blocked by|subtasks?|sub-tasks?)\b', name))) and not any(word in name for word in ('summary', 'description', 'count', 'name'))


def display_fields(fields, issue, index):
    """Return display segments by occurrence; raw CSV remains separately available."""
    result = {}
    for name, values in fields.items():
        occurrences = []
        for value in values:
            # Keys can occur in any column; bare numbers require a relationship header.
            matches = list(KEY.finditer(value))
            if reference_field(name):
                matches += [m for m in NUMBER.finditer(value) if not any(k.start() <= m.start() < k.end() for k in matches)]
            matches.sort(key=lambda m: m.start())
            parts, start = [], 0
            for match in matches:
                if start < match.start():
                    parts.append({'text': value[start:match.start()]})
                token = match.group()
                target, reason = index.resolve(token, issue['project_key'])
                if 'parent' in header_key(name) and token in (issue.get('parent_id'), issue.get('parent_reference')) and issue.get('parent_in_export'):
                    target, reason = index.keys.get(issue['parent_key'].casefold()), ''
                if target:
                    parts.append({'text': target['summary'], 'key': target['key']})
                elif reference_field(name):
                    parts.append({'text': 'Ambiguous ticket reference' if reason == 'ambiguous' else (issue.get('parent_summary') if 'parent' in header_key(name) else '') or 'Ticket not included in export', 'reference': token, 'reason': reason})
                else:
                    parts.append({'text': token})
                start = match.end()
            if start < len(value):
                parts.append({'text': value[start:]})
            occurrences.append(parts or [{'text': value or '(empty)'}])
        result[name] = occurrences
    return result
