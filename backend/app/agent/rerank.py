"""Lightweight transparent relevance reranking plus result diversity; no extra model download."""

import re


def rank(chunks, allowed, fused, cosines, query, query_tokens, limit):
    terms = set(query_tokens)
    maximum = max(fused.values(), default=1)
    by_issue = {}
    for c in chunks:
        ident = c['id']
        if ident not in fused:
            continue
        issue = allowed[c['issue_key']]
        title = set(re.findall(r'\w+', issue['summary'].casefold()))
        content = set(re.findall(r'\w+', c['content'].casefold()))
        title_coverage = len(terms & title) / max(1, len(terms))
        coverage = len(terms & content) / max(1, len(terms))
        phrase = 1 if query.strip().casefold() in issue['summary'].casefold() else 0
        score = (
            0.35 * fused[ident] / maximum
            + 0.20 * max(0, cosines.get(ident, 0))
            + 0.25 * title_coverage
            + 0.15 * coverage
            + 0.05 * phrase
        )
        candidate = (score, c, title)
        previous = by_issue.get(c['issue_key'])
        if not previous or (score, ident) > (previous[0], previous[1]['id']):
            by_issue[c['issue_key']] = candidate
    remaining = list(by_issue.values())
    chosen = []
    while remaining and len(chosen) < limit:

        def diverse(item):
            redundancy = max((len(item[2] & p[2]) / max(1, len(item[2] | p[2])) for p in chosen), default=0)
            return (item[0] - 0.10 * redundancy, item[0], item[1]['id'])

        best = max(remaining, key=diverse)
        remaining.remove(best)
        chosen.append(best)
    return [(c, round(score, 5)) for score, c, _ in chosen]
