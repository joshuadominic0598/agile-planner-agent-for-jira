"""Safe value-count analytics for arbitrary exported fields, without unit inference."""
from collections import Counter


def values(fields, name):
    return set(v.strip() for v in fields.get(name, []) if v.strip())


def catalog(records):
    stats = {}
    for record in records.values():
        for name, raw in record.items():
            item = stats.setdefault(name, {'name': name, 'populated': 0, 'distinct': set(), 'longest': 0, 'occurrences': 0})
            found = values(record, name)
            item['populated'] += bool(found)
            item['distinct'].update(found)
            item['longest'] = max(item['longest'], max(map(len, found), default=0))
            item['occurrences'] = max(item['occurrences'], len(raw))
    return [{'name': s['name'], 'populated': s['populated'], 'distinct': len(s['distinct']), 'occurrences': s['occurrences'], 'chartable': 0 < len(s['distinct']) <= 50 and s['longest'] <= 120} for s in stats.values()]


def breakdown(records, name):
    if not any(name in r for r in records.values()):
        raise ValueError('Field not found in this export.')
    counts = Counter()
    missing = 0
    multiple = False
    for record in records.values():
        found = values(record, name)
        counts.update(found)
        missing += not found
        multiple = multiple or len(found) > 1
    if len(counts) > 50 or any(len(v) > 120 for v in counts):
        raise ValueError('Charts support fields with up to 50 distinct short values. This field remains available in issue details.')
    return {'field': name, 'issues': len(records), 'populated': len(records) - missing, 'multiple_values': multiple, 'values': [{'value': value, 'count': count, 'missing': False} for value, count in counts.most_common()] + ([{'value': '', 'count': missing, 'missing': True}] if missing else [])}


def matches(record, name, value, missing=False):
    found = values(record, name)
    return not found if missing else value in found
