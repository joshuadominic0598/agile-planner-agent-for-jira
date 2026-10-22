"""Potential duplicates among To Do tickets; content similarity is a review signal."""

import hashlib
import json
import re
from array import array
from difflib import SequenceMatcher
from html import unescape

from fastapi import APIRouter, HTTPException, Query

from . import columns, store, vector_store
from .agent import index

router = APIRouter(prefix='/api/datasets/{dataset_id}', tags=['Duplicate review'])
VERSION = 1


def normalize(text):
    return ' '.join(re.findall(r'\w+', unescape(re.sub('<[^>]+>', ' ', text)).casefold()))


def eligible(issue):
    category = normalize(issue.get('category', ''))
    status = normalize(issue.get('status', ''))
    if status in {'done', 'completed', 'closed', 'production', 'prod'}:
        return False
    return category in {'to do', 'todo'} if category else status in {'to do', 'todo'}


def compute(dataset_id, project=''):
    state = index.require_ready(dataset_id)
    version = f'{VERSION}:{state["metadata"]["built_at"]}'
    cached = store.mongo().duplicate_reviews.find_one(
        {'dataset_id': dataset_id, 'project': project, 'version': version}, {'_id': 0}
    )
    if cached:
        return cached
    rows = [i for i in store.summaries(dataset_id, project or None) if eligible(i)]
    fields = store.field_rows(dataset_id, project or None)
    with vector_store.connect() as db:
        chunks = db.execute(
            'SELECT issue_key,dense,vector,id FROM agent_chunks WHERE dataset_id=?', (dataset_id,)
        ).fetchall()
    vectors = {}
    eligible_keys = {row['key'] for row in rows}
    for chunk in chunks:
        if chunk['issue_key'] not in eligible_keys:
            continue
        if chunk['id'].endswith(':0'):
            vectors[chunk['issue_key']] = (
                array('f', chunk['dense']) if chunk['dense'] else None,
                json.loads(chunk['vector']),
            )
    documents = {}
    for row in rows:
        title = normalize(row['summary'])
        desc = normalize('\n'.join(columns.values(fields.get(row['key'], {}), 'description')))
        words = desc.split()
        shingles = set(zip(words, words[1:], words[2:]))
        documents[row['key']] = (title, desc, set(title.split()), shingles)
    pairs = []
    for n, left in enumerate(rows):
        a, ad, words, ash = documents[left['key']]
        for right in rows[n + 1 :]:
            if left['project_key'] != right['project_key']:
                continue
            b, bd, other, bsh = documents[right['key']]
            exact = bool(a and a == b and ad == bd)
            overlap = len(words & other) / max(1, len(words | other))
            if not exact and overlap < 0.12:
                # Dense vectors still detect paraphrases without literal title overlap.
                va = vectors.get(left['key'], (None, {}))[0]
                if va is None:
                    continue
            title_score = 1.0 if exact else SequenceMatcher(None, a[:512], b[:512], autojunk=True).ratio()
            desc_score = (
                (2 * len(ash & bsh) / max(1, len(ash) + len(bsh)))
                if ash and bsh
                else (1.0 if ad and ad == bd else None)
            )
            va, sa = vectors.get(left['key'], (None, {}))
            vb, sb = vectors.get(right['key'], (None, {}))
            semantic = (
                sum(x * y for x, y in zip(va, vb))
                if va is not None and vb is not None and len(va) == len(vb)
                else None
            )
            lexical = sum(value * sb.get(term, 0) for term, value in sa.items())
            content = title_score if desc_score is None else 0.45 * title_score + 0.55 * desc_score
            similarity = 1.0 if exact else max(content, semantic or 0)
            if not exact and not (
                content >= 0.86
                and title_score >= 0.6
                or semantic is not None
                and semantic >= 0.9
                and (semantic >= 0.96 or overlap >= 0.12 or desc_score is not None and desc_score >= 0.5)
            ):
                continue
            pairs.append(
                {
                    'id': hashlib.sha256(':'.join(sorted([left['key'], right['key']])).encode()).hexdigest()[
                        :20
                    ],
                    'left': {
                        k: left.get(k)
                        for k in (
                            'key',
                            'summary',
                            'status',
                            'category',
                            'assignee',
                            'reporter',
                            'project_key',
                        )
                    },
                    'right': {
                        k: right.get(k)
                        for k in (
                            'key',
                            'summary',
                            'status',
                            'category',
                            'assignee',
                            'reporter',
                            'project_key',
                        )
                    },
                    'exact': exact,
                    'similarity': round(similarity, 4),
                    'title_similarity': round(title_score, 4),
                    'description_similarity': round(desc_score, 4) if desc_score is not None else None,
                    'semantic_similarity': round(semantic, 4) if semantic is not None else None,
                    'lexical_similarity': round(lexical, 4),
                    'reason': 'Same normalized title and description'
                    if exact
                    else 'Similar ticket content; review before treating as duplicate',
                }
            )
    pairs.sort(key=lambda p: (p['exact'], p['similarity']), reverse=True)
    result = {
        'dataset_id': dataset_id,
        'project': project,
        'version': version,
        'index_built_at': state['metadata']['built_at'],
        'eligible_tickets': len(rows),
        'pairs': pairs[:1000],
        'truncated': len(pairs) > 1000,
        'method': 'Indexed semantic vectors + normalized title/description'
        if state['metadata'].get('embedding_provider') != 'local'
        else 'Normalized title/description + indexed lexical vectors (semantic embeddings not configured)',
    }
    store.mongo().duplicate_reviews.replace_one(
        {'dataset_id': dataset_id, 'project': project}, result, upsert=True
    )
    return result


@router.get('/duplicates')
def duplicates(
    dataset_id: str,
    project: str = '',
    threshold: float = Query(default=0.88, ge=0.8, le=1),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=5, ge=1, le=20),
):
    if not store.dataset(dataset_id):
        raise HTTPException(404, 'Import not found.')
    try:
        result = compute(dataset_id, project)
    except index.RetrievalError as exc:
        return {'ready': False, 'message': str(exc), 'pairs': [], 'total': 0}
    pairs = [p for p in result['pairs'] if p['similarity'] >= threshold]
    start = (page - 1) * limit
    return {
        **result,
        'ready': True,
        'pairs': pairs[start : start + limit],
        'total': len(pairs),
        'page': page,
        'limit': limit,
        'definition': 'Only current To Do-category tickets, or exact To Do status when category is missing. Completed and in-progress work is excluded. Similarity is not proof of duplication.',
    }
