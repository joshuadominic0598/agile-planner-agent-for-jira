"""Overview ticket finder: exact identifiers, discovered filters, then narrative retrieval."""

import re
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request

from . import analytics, store
from .agent import index

router = APIRouter(prefix='/api/datasets/{dataset_id}/ticket-search', tags=['Ticket search'])
FILTERS = ('project', 'status', 'category', 'type', 'priority', 'assignee', 'reporter', 'sprint')
METADATA = {'project': 'project_key', 'sprint': 'sprints'}


def source(dataset_id):
    data = store.dataset(dataset_id)
    if not data:
        raise HTTPException(404, 'Import a Jira export before searching tickets.')
    if data['status'] != 'ready':
        raise HTTPException(409, 'Wait for this import to finish before searching.')


def discovered(rows):
    return {
        field: sorted(
            {
                str(value)
                for row in rows
                for value in (
                    row['sprints'] if field == 'sprint' else [row.get(METADATA.get(field, field), '')]
                )
                if value
            },
            key=analytics.sprint_sort if field == 'sprint' else str.casefold,
        )
        for field in FILTERS
    }


def identifier(text):
    token = re.sub(r'^(?:ticket|issue|work item)\s*#?\s*', '', text.strip(), flags=re.I).lstrip('#').strip()
    if token.isdigit():
        return '', str(int(token))
    match = re.fullmatch(r'([A-Za-z][A-Za-z0-9_]*?)[ -]*(\d+)', token)
    return (match[1].casefold(), str(int(match[2]))) if match else None


def interpret(text, options):
    remaining, inferred = text.strip(), []
    for value in sorted(options['priority'], key=len, reverse=True):
        pattern = r'\b(?:priority\s*[:=]?\s*' + re.escape(value) + r'|' + re.escape(value) + r'\s+priority)\b'
        if re.search(pattern, remaining, re.I):
            remaining = re.sub(pattern, ' ', remaining, flags=re.I).strip()
            inferred.append({'field': 'priority', 'value': value, 'source': 'query'})
            break
    remaining = re.sub(r'^(?:show(?: me)?|find|list)\s+', '', remaining, flags=re.I).strip()
    generic = re.sub(
        r'^(?:all\s+)?(?:tickets?|issues?|work items?)\s*|\s+(?:tickets?|issues?|work items?)$',
        '',
        remaining,
        flags=re.I,
    ).strip()
    if not generic and inferred:
        remaining = ''
    for field in ('status', 'category', 'priority', 'type'):
        for value in sorted(options[field], key=len, reverse=True):
            normalized = generic.casefold().strip()
            if normalized == value.casefold() or field == 'type' and normalized == value.casefold() + 's':
                inferred.append({'field': field, 'value': value, 'source': 'query'})
                remaining = ''
                break
            tagged = re.fullmatch(re.escape(field) + r'\s*[:=]\s*' + re.escape(value), remaining, re.I)
            if tagged:
                inferred.append({'field': field, 'value': value, 'source': 'query'})
                remaining = ''
                break
        if not remaining:
            break
    return remaining, inferred


def snippet(text, terms):
    text = re.sub(r'\s+', ' ', text).strip()
    first = next((match.start() for term in terms if (match := re.search(re.escape(term), text, re.I))), 0)
    start = max(0, first - 65)
    return ('…' if start else '') + text[start : start + 230] + ('…' if len(text) > start + 230 else '')


@router.get('/options')
def options(dataset_id: str):
    source(dataset_id)
    return {'fields': discovered(store.summaries(dataset_id))}


@router.get('')
def search(
    dataset_id: str,
    request: Request,
    q: str = Query(default='', max_length=300),
    project: str = Query(default='', max_length=100),
    status: str = Query(default='', max_length=200),
    category: str = Query(default='', max_length=200),
    issue_type: str = Query(default='', max_length=200),
    priority: str = Query(default='', max_length=200),
    assignee: str = Query(default='', max_length=200),
    reporter: str = Query(default='', max_length=200),
    sprint: str = Query(default='', max_length=200),
    semantic: bool = False,
    limit: int = Query(default=12, ge=1, le=30),
):
    source(dataset_id)
    rows = store.summaries(dataset_id)
    reference = identifier(q) if q.strip() else None
    text, inferred = (q.strip(), []) if reference else interpret(q, discovered(rows))
    reference = reference or (identifier(text) if text else None)
    chosen = dict(
        project=project,
        status=status,
        category=category,
        type=issue_type,
        priority=priority,
        assignee=assignee,
        reporter=reporter,
        sprint=sprint,
    )
    applied = [
        {'field': field, 'value': value, 'source': 'filter'} for field, value in chosen.items() if value
    ] + inferred
    conditions = [
        {
            'summary.' + METADATA.get(item['field'], item['field']): {
                '$regex': '^' + re.escape(item['value']) + '$',
                '$options': 'i',
            }
        }
        for item in applied
    ]
    match = {'dataset_id': dataset_id, **({'$and': conditions} if conditions else {})}
    documents = list(store.mongo().issues.find(match, {'_id': 0, 'summary': 1, 'details.description': 1}))
    eligible = {doc['summary']['key']: doc for doc in documents}
    terms = list(dict.fromkeys(index.tokens(text)))[:20]
    notice, found = '', {}
    if reference:
        prefix, number = reference
        for doc in documents:
            row = doc['summary']
            key_prefix, suffix = row['key'].rsplit('-', 1)
            if prefix and key_prefix.casefold() != prefix:
                continue
            if (suffix.isdigit() and str(int(suffix)) == number) or (
                not prefix and row.get('issue_id', '').isdigit() and str(int(row['issue_id'])) == number
            ):
                found[row['key']] = {
                    'ticket': row,
                    'match': 'Ticket number',
                    'excerpt': '',
                    '_rank': (0, row['key']),
                }
        if len(found) > 1:
            notice = 'Several ticket identifiers match. Choose a result or narrow the project filter.'
    elif not text:
        for doc in documents:
            row = doc['summary']
            found[row['key']] = {
                'ticket': row,
                'match': 'Filter match',
                'excerpt': '',
                '_rank': (
                    0,
                    -int(row['key'].rsplit('-', 1)[-1]) if row['key'].rsplit('-', 1)[-1].isdigit() else 0,
                    row['key'],
                ),
            }
    else:
        for doc in documents:
            row, description = doc['summary'], doc.get('details', {}).get('description', '')
            title_terms = sum(term in row['summary'].casefold() for term in terms)
            desc_terms = sum(term in description.casefold() for term in terms)
            if not title_terms and not desc_terms:
                continue
            tier = (
                (
                    0
                    if text.casefold() == row['summary'].casefold()
                    else 1
                    if text.casefold() in row['summary'].casefold() or title_terms == len(terms)
                    else 2
                )
                if title_terms
                else 3
            )
            found[row['key']] = {
                'ticket': row,
                'match': 'Title match' if title_terms else 'Description match',
                'excerpt': snippet(description, terms),
                '_rank': (tier, -title_terms, -desc_terms, row['key']),
            }
    keyword_count = len(found)
    index_state = {'status': 'not_used', 'metadata': {}}
    if text and not reference:
        try:
            index_state = index.status(dataset_id)
        except (sqlite3.DatabaseError, OSError, index.RetrievalError):
            index_state['status'] = 'unavailable'
    can_expand = bool(
        text and not reference and len(text) >= 3 and eligible and index_state['status'] == 'ready'
    )
    mode = 'identifier' if reference else 'metadata' if not text else 'keyword'
    if semantic and can_expand:
        try:
            matches = index.hybrid_search(
                dataset_id,
                text,
                issue_keys=list(eligible),
                limit=min(limit, 12),
                cache=request.app.state.retrieval_cache,
            )
            for result in matches:
                if result['key'] not in found and result['key'] in eligible:
                    found[result['key']] = {
                        'ticket': eligible[result['key']]['summary'],
                        'match': 'Semantic match'
                        if index_state['metadata']['embedding_provider'] != 'local'
                        else 'Text similarity',
                        'excerpt': snippet(
                            eligible[result['key']].get('details', {}).get('description', '')
                            or result['excerpt'],
                            terms,
                        ),
                        '_rank': (4, -result.get('rerank_score', 0), result['key']),
                    }
            mode = 'hybrid' if index_state['metadata']['embedding_provider'] != 'local' else 'text_similarity'
        except (index.RetrievalError, sqlite3.DatabaseError, OSError):
            notice = 'Similar-ticket search is unavailable right now. Keyword matches and filters still work.'
    elif text and not reference and index_state['status'] != 'ready':
        notice = 'Keyword matches are available. Prepare the ticket index in Sprint Agent → Configure to enable similarity search.'
    items = sorted(found.values(), key=lambda item: item['_rank'])[:limit]
    for item in items:
        item.pop('_rank')
    return {
        'items': items,
        'returned': len(items),
        'total': len(found) if reference or not text else None,
        'keyword_matches': keyword_count,
        'applied_filters': applied,
        'interpreted_query': text,
        'highlight_terms': terms,
        'can_expand': can_expand,
        'mode': mode,
        'notice': notice,
        'semantic_index': index_state['status'],
    }
