"""Complete-scope, reproducible title/description theme suggestions, never metadata inference."""

import math
import re
from collections import Counter

STOP = set(
    'a an and are as at be by can could do does for from find give how i in is it me my of on or please related show similar tell that the their them there these this ticket tickets issue issues to us what which with work items would you about'.split()
)
EXTRA = set(
    'title description story task issue ticket please add new update create implement support changes work related using use data'.split()
)


def requested(text):
    return bool(
        re.search(
            r'\b(?:classify|categor[iz]e|cluster)\b|\b(?:group|split|break down)\b.*\b(?:topics?|themes?|areas?|work)\b|\bwhat (?:topics?|themes?)\b',
            text,
            re.I,
        )
    )


def group(records):
    """Accept stable narrative records; storage and event handling stay at the boundary."""
    if len(records) > 5000:
        raise ValueError(
            'Theme analysis supports up to 5,000 tickets. Narrow the project, sprint or filters first; no tickets were silently sampled.'
        )
    docs = []
    df = Counter()
    for issue in sorted(records, key=lambda i: i['key']):
        raw = issue['summary'] + ' ' + issue['description'][:6000]
        title = re.findall(r'\w+', issue['summary'].lower())
        body = re.findall(r'\w+', raw.lower())
        words = [
            w for w in body + title * 2 if w not in EXTRA and w not in STOP and not w.isdigit() and len(w) > 2
        ]
        count = Counter(dict(Counter(words).most_common(160)))
        docs.append((issue, count))
        df.update(count.keys())
    n = len(docs)
    vectors = []
    for _, count in docs:
        vec = {t: (1 + math.log(c)) * math.log(1 + (n + 1) / (df[t] + 1)) for t, c in count.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1
        vectors.append({t: v / norm for t, v in vec.items()})

    def dot(a, b):
        return sum(v * b.get(t, 0) for t, v in a.items())

    k = min(n, 6, max(2, round(math.sqrt(n / 3)))) if n else 0
    seeds = [max(range(n), key=lambda j: len(vectors[j]))] if n else []
    while len(seeds) < k:
        remaining = [j for j in range(n) if j not in seeds]
        chosen = min(remaining, key=lambda j: max(dot(vectors[j], vectors[c]) for c in seeds))
        seeds.append(chosen)
    centers = [vectors[j] for j in seeds]
    labels = []
    for _ in range(12):
        updated = [max(range(k), key=lambda c: dot(vec, centers[c])) for vec in vectors]
        if updated == labels:
            break
        labels = updated
        centers = []
        for c in range(k):
            center = Counter()
            for j, vec in enumerate(vectors):
                if labels[j] == c:
                    center.update(vec)
            norm = math.sqrt(sum(v * v for v in center.values())) or 1
            centers.append({t: v / norm for t, v in center.items()})
    groups = []
    for c in range(k):
        members = [j for j in range(n) if labels[j] == c]
        if not members:
            continue
        terms = [t for t, _ in sorted(centers[c].items(), key=lambda x: (-x[1], x[0]))[:4]]
        example_ids = sorted(members, key=lambda j: -dot(vectors[j], centers[c]))[:2]
        examples = [{f: docs[j][0][f] for f in ('key', 'summary', 'status')} for j in example_ids]
        groups.append(
            {
                'name': ' / '.join(terms) or 'No narrative text',
                'count': len(members),
                'examples': examples,
                'ticket_keys': [docs[j][0]['key'] for j in members],
            }
        )
    groups.sort(key=lambda g: (-g['count'], g['name']))
    return {
        'total': n,
        'themes': groups,
        'method': 'TF-IDF cosine clustering over title/description, with data-derived keyword labels; suggested themes, not configured Jira categories. Every ticket belongs to one group.',
    }
