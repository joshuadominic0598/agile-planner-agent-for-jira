"""SQLite vector/FTS index plus explicit issue/entity graph; immutable per snapshot."""

import hashlib
import json
import math
import re
from array import array
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from functools import lru_cache

import httpx

from .. import analytics, columns, references, store, vector_store
from . import rerank, retrieval_cache
from .config import embedding_config, embedding_signature
from .embedding_profiles import apply_profile, ticket_chunks
from .ports import RetrievalCache

VERSION = 6
STOP = set(
    'a an and are as at be by can could do does for from find give how i in is it me my of on or please related show similar tell that the their them there these this ticket tickets issue issues to us what which with work items would you about'.split()
)
IMPORTANT = re.compile(
    r'acceptance|labels?|components?|fix versions?|affects versions?|environment|epic name', re.I
)
TOPIC = re.compile(
    r'^(?:custom field \()?((?:labels?|component(?:s|/s)?|fix version(?:s|/s)?))(?:\))?$', re.I
)


class RetrievalError(ValueError):
    pass


def dataset_embedding_config(dataset_id):
    source = store.dataset(dataset_id) or {}
    return apply_profile(embedding_config(), source.get('embedding_preset'))


def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS agent_indices(dataset_id TEXT PRIMARY KEY,status TEXT NOT NULL,progress INTEGER NOT NULL DEFAULT 0,message TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS agent_chunks(id TEXT PRIMARY KEY,dataset_id TEXT NOT NULL,issue_key TEXT NOT NULL,project TEXT NOT NULL,content TEXT NOT NULL,vector TEXT NOT NULL,dense BLOB);
    CREATE INDEX IF NOT EXISTS agent_chunks_scope ON agent_chunks(dataset_id,project);
    CREATE VIRTUAL TABLE IF NOT EXISTS agent_fts USING fts5(chunk_id UNINDEXED,dataset_id UNINDEXED,project UNINDEXED,content);
    CREATE TABLE IF NOT EXISTS agent_terms(dataset_id TEXT NOT NULL,term TEXT NOT NULL,idf REAL NOT NULL,PRIMARY KEY(dataset_id,term));
    CREATE TABLE IF NOT EXISTS agent_nodes(dataset_id TEXT NOT NULL,id TEXT NOT NULL,kind TEXT NOT NULL,label TEXT NOT NULL,project TEXT NOT NULL,issue_key TEXT,PRIMARY KEY(dataset_id,id));
    CREATE TABLE IF NOT EXISTS agent_edges(dataset_id TEXT NOT NULL,source TEXT NOT NULL,target TEXT NOT NULL,relation TEXT NOT NULL,PRIMARY KEY(dataset_id,source,target,relation));
    CREATE INDEX IF NOT EXISTS agent_edges_source ON agent_edges(dataset_id,source);
    CREATE INDEX IF NOT EXISTS agent_edges_target ON agent_edges(dataset_id,target);
    """)
    db.execute(
        "UPDATE agent_indices SET status='failed',message='Indexing interrupted by restart. Prepare the index again.' WHERE status='building'"
    )


def tokens(text):
    return [t for t in re.findall(r'\w+', text.lower(), re.UNICODE) if len(t) > 1 and t not in STOP][:8000]


def status(dataset_id):
    with vector_store.connect() as db:
        row = db.execute('SELECT * FROM agent_indices WHERE dataset_id=?', (dataset_id,)).fetchone()
    if not row:
        return {
            'status': 'missing',
            'progress': 0,
            'message': 'Agent unavailable: prepare the ticket index first.',
            'metadata': {},
        }
    result = dict(row)
    result['metadata'] = json.loads(result['metadata'])
    if result['status'] == 'ready':
        source = store.dataset(dataset_id)
        if (
            result['metadata'].get('version') != VERSION
            or result['metadata'].get('sha256') != source['metadata'].get('sha256')
            or embedding_signature(result['metadata'].get('embedding_signature', ''))
            != embedding_signature(dataset_embedding_config(dataset_id)['signature'])
        ):
            result.update(status='stale', message='Index settings changed. Rebuild the ticket index.')
    return result


def reserve(dataset_id, preset=None):
    with vector_store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT status FROM agent_indices WHERE dataset_id=?', (dataset_id,)).fetchone()
        if row and row[0] == 'building':
            return False
        if preset is not None:
            if preset not in {'small', 'large', 'lexical'}:
                raise RetrievalError('Choose a supported embedding model.')
            # Validate the local endpoint before saving the user's choice.
            apply_profile(embedding_config(), preset)
            store.mongo().datasets.update_one({'id': dataset_id}, {'$set': {'embedding_preset': preset}})
        db.execute(
            "INSERT INTO agent_indices(dataset_id,status,progress,message) VALUES(?,'building',0,'Preparing ticket text and relationships') ON CONFLICT(dataset_id) DO UPDATE SET status='building',progress=0,message=excluded.message",
            (dataset_id,),
        )
    return True


def progress(dataset_id, percent, message):
    with vector_store.connect() as db:
        db.execute(
            'UPDATE agent_indices SET progress=?,message=? WHERE dataset_id=?', (percent, message, dataset_id)
        )


def ticket_document(issue, fields):
    lines = [f'{issue["key"]} — {issue["summary"]}']
    for field in (
        'project_key',
        'type',
        'status',
        'category',
        'priority',
        'resolution',
        'assignee',
        'reporter',
        'updated',
    ):
        if issue.get(field):
            lines.append(f'{field}: {issue[field]}')
    if issue['sprints']:
        lines.append('sprints: ' + ', '.join(issue['sprints']))
    descriptions = columns.values(fields, 'description')
    if descriptions:
        lines.append('Description: ' + '\n'.join(descriptions)[:7500])
    for name, values in fields.items():
        if IMPORTANT.search(name):
            found = list(dict.fromkeys(v.strip() for v in values if v.strip()))
            if found:
                lines.append(name + ': ' + '; '.join(found)[:2000])
    comments = columns.values(fields, 'comments')
    if comments:
        lines.append(
            'Comments (last 3 populated CSV occurrences, not a chronological assertion): '
            + '\n'.join(comments[-3:])[:3000]
        )
    return '\n'.join(lines)[:16000]


def document_sections(issue, fields):
    """Index narrative evidence and exported file references, never attachment bytes."""
    from .ticket_context import CRITERIA, attachments

    criteria = [
        f'{name}: {value}'
        for name, values in fields.items()
        if CRITERIA.search(name)
        for value in values
        if value.strip()
    ]
    comments = []
    for name, values in fields.items():
        if name not in columns.matching_fields(fields, 'comments'):
            continue
        for value in values:
            if value.strip():
                parts = value.split(';', 2)
                text = parts[2] if len(parts) == 3 and re.match(r'^\d{1,4}[/\-]', value) else value
                comments.append(f'{name}: {text}')
    files = attachments(fields)
    return {
        'Description': '\n'.join(columns.values(fields, 'description')),
        'Acceptance criteria': '\n'.join(criteria),
        'Comments': '\n'.join(comments),
        'Attachment references (contents unavailable)': '; '.join(item['name'] for item in files['items']),
    }


def document(issue, fields):
    sections = document_sections(issue, fields)
    return '\n'.join([f'Title: {issue["summary"]}', *(f'{k}: {v}' for k, v in sections.items())])


def normalize(vector):
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def remote_embeddings(texts, config=None, query=False, cache: RetrievalCache | None = None):
    config = config or embedding_config()
    vector_key = (
        retrieval_cache.key(
            [
                config['provider'],
                config['model'],
                config['base'],
                hashlib.sha256(config.get('key', '').encode()).hexdigest(),
                texts,
            ]
        )
        if query
        else None
    )
    cached = cache.get('vectors', vector_key) if cache is not None and vector_key else None
    if cached is not None:
        return cached
    if config['provider'] not in {'openai', 'compatible'} or not config['model'] or not config['base']:
        raise RetrievalError(
            'Configure the embedding provider, model and base URL before building semantic vectors.'
        )
    if config['provider'] == 'openai' and not config['key']:
        raise RetrievalError('The embedding API key is missing.')
    from .provider import validate_base

    validate_base(config['base'])
    if config['model'].split(':')[0] == 'embeddinggemma':
        texts = [('task: search result | query: ' if query else 'title: none | text: ') + t for t in texts]
    elif config['model'].split(':')[0] == 'qwen3-embedding' and query:
        texts = [
            'Instruct: Retrieve Jira ticket passages relevant to the search query.\nQuery: ' + t
            for t in texts
        ]
    headers = {'Authorization': f'Bearer {config["key"]}'} if config['key'] else {}
    try:
        with httpx.Client(timeout=120 if config.get('ollama') else 45) as client:
            response = client.post(
                config['base'] + ('/api/embed' if config.get('ollama') else '/embeddings'),
                headers=headers,
                json={
                    'model': config['model'],
                    'input': texts,
                    **({'truncate': False} if config.get('ollama') else {}),
                },
            )
            response.raise_for_status()
            data = response.json()
            rows = (
                [{'index': i, 'embedding': v} for i, v in enumerate(data['embeddings'])]
                if config.get('ollama')
                else sorted(data['data'], key=lambda r: r['index'])
            )
            vectors = [r['embedding'] for r in rows]
            if (
                [r['index'] for r in rows] != list(range(len(texts)))
                or len(vectors) != len(texts)
                or not vectors
                or not vectors[0]
                or len(vectors[0]) > 8192
                or any(
                    len(v) != len(vectors[0])
                    or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in v)
                    for v in vectors
                )
            ):
                raise ValueError('Invalid embedding response')
            normalized = [normalize(v) for v in vectors]
            if cache is not None and vector_key:
                cache.put('vectors', vector_key, normalized)
            return normalized
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        if config.get('ollama'):
            raise RetrievalError(
                f'Local embedding failed. Start Ollama and run ollama pull {config["model"]}, '
                'then retry. Inputs exceeding the model context are rejected, never silently truncated. '
                'Ticket text is not sent to a cloud fallback.'
            ) from exc
        raise RetrievalError(
            'Embedding connection failed. Check the model, API key and provider settings, then retry.'
        ) from exc


def build(dataset_id):
    try:
        source = store.dataset(dataset_id)
        issues = store.summaries(dataset_id)
        if not issues or not source or source['status'] != 'ready':
            raise RetrievalError('Agent unavailable: import a valid Jira CSV first.')
        raw = store.field_rows(dataset_id)
        refs = references.Index(issues)
        config = dataset_embedding_config(dataset_id)
        chunks, nodes, edges = [], {}, set()
        for issue in issues:
            key, project = issue['key'], issue['project_key']
            nodes[key] = (key, 'issue', issue['summary'], project, key)
            for n, content in enumerate(
                ticket_chunks(
                    document_sections(issue, raw[key]),
                    issue['summary'],
                    config['chunk_characters'],
                    config['chunk_overlap'],
                )
            ):
                chunks.append(
                    {
                        'id': f'{dataset_id}:{key}:{n}',
                        'key': key,
                        'project': project,
                        'content': content,
                        'tf': Counter(tokens(content)),
                    }
                )
            if issue.get('parent_in_export') and not issue.get('hierarchy_warning'):
                edges.add((key, issue['parent_key'], 'parent'))
            for name, values in raw[key].items():
                topic = TOPIC.match(name.strip())
                if topic:
                    for value in set(v.strip() for v in values if v.strip()):
                        ident = 'topic:' + hashlib.sha256(f'{project}:{name}:{value}'.encode()).hexdigest()
                        nodes[ident] = (ident, 'topic', f'{name}: {value}', project, None)
                        edges.add((key, ident, name))
                if (
                    references.reference_field(name)
                    and 'parent' not in name.casefold()
                    and columns.header_key(name) not in {'issue id', 'work item id'}
                ):
                    for value in values:
                        matches = references.KEY.findall(value)
                        if value.strip().isdigit():
                            matches.append(value.strip())
                        for token in matches:
                            target, _ = refs.resolve(token, project)
                            if target and target['key'] != key:
                                edges.add((key, target['key'], name))
        progress(dataset_id, 25, 'Building vector and keyword index')
        df = Counter(term for c in chunks for term in c['tf'])
        idf = {term: math.log((1 + len(chunks)) / (1 + count)) + 1 for term, count in df.items()}
        for chunk in chunks:
            weights = {term: (1 + math.log(count)) * idf[term] for term, count in chunk['tf'].items()}
            norm = math.sqrt(sum(w * w for w in weights.values())) or 1
            chunk['vector'] = json.dumps({t: round(w / norm, 7) for t, w in weights.items()})
            chunk['dense'] = None
        dimensions = None
        if config['provider'] != 'local':
            batch_size = config['batch_size']
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                vectors = remote_embeddings([c['content'] for c in batch], config)
                if dimensions and dimensions != len(vectors[0]):
                    raise RetrievalError(
                        'Embedding dimensions changed during indexing. Retry with a consistent provider.'
                    )
                dimensions = len(vectors[0])
                for c, vector in zip(batch, vectors):
                    c['dense'] = array('f', vector).tobytes()
                progress(
                    dataset_id, 30 + int(50 * (start + len(batch)) / len(chunks)), 'Embedding ticket chunks'
                )
        progress(dataset_id, 85, 'Saving graph and retrieval index')
        meta = {
            'version': VERSION,
            'sha256': source['metadata']['sha256'],
            'embedding_signature': config['signature'],
            'embedding_provider': config['provider'],
            'embedding_model': config['model']
            if config['provider'] != 'local'
            else 'TF-IDF (lexical vectors)',
            'dimensions': dimensions,
            'similarity_floor': 0.25 if config['model'].split(':')[0] == 'embeddinggemma' else 0.45,
            'tickets': len(issues),
            'chunks': len(chunks),
            'nodes': len(nodes),
            'edges': len(edges),
            'indexed_fields': [
                'Summary',
                'Description',
                'Acceptance criteria',
                'Comments',
                'Attachment references',
            ],
            'embedding_preset': config['preset'],
            'chunk_characters': config['chunk_characters'],
            'chunk_overlap': config['chunk_overlap'],
            'chunk_policy': 'one ticket per chunk; repeated title and field labels; no narrative truncation',
            'built_at': datetime.now(timezone.utc).isoformat(),
        }
        with vector_store.connect() as db:
            for table in ('agent_chunks', 'agent_fts', 'agent_terms', 'agent_nodes', 'agent_edges'):
                db.execute(f'DELETE FROM {table} WHERE dataset_id=?', (dataset_id,))
            db.executemany(
                'INSERT INTO agent_chunks VALUES(?,?,?,?,?,?,?)',
                [
                    (c['id'], dataset_id, c['key'], c['project'], c['content'], c['vector'], c['dense'])
                    for c in chunks
                ],
            )
            db.executemany(
                'INSERT INTO agent_fts(chunk_id,dataset_id,project,content) VALUES(?,?,?,?)',
                [(c['id'], dataset_id, c['project'], c['content']) for c in chunks],
            )
            db.executemany(
                'INSERT INTO agent_terms VALUES(?,?,?)', [(dataset_id, t, v) for t, v in idf.items()]
            )
            db.executemany(
                'INSERT INTO agent_nodes VALUES(?,?,?,?,?,?)', [(dataset_id, *n) for n in nodes.values()]
            )
            db.executemany('INSERT INTO agent_edges VALUES(?,?,?,?)', [(dataset_id, *e) for e in edges])
            db.execute(
                "UPDATE agent_indices SET status='ready',progress=100,message='Ticket index ready',metadata=? WHERE dataset_id=?",
                (json.dumps(meta), dataset_id),
            )
        cached_chunks.cache_clear()
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, RetrievalError)
            else 'Indexing failed. Analytics is still available; retry preparing the agent index.'
        )
        with vector_store.connect() as db:
            db.execute(
                "UPDATE agent_indices SET status='failed',message=? WHERE dataset_id=?", (message, dataset_id)
            )


def require_ready(dataset_id):
    result = status(dataset_id)
    if result['status'] != 'ready':
        raise RetrievalError(result['message'])
    return result


@lru_cache(maxsize=2)
def cached_chunks(dataset_id, built_at):
    with vector_store.connect() as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM agent_chunks WHERE dataset_id=?', (dataset_id,))]
    for row in rows:
        row['sparse'] = json.loads(row['vector'])
        dense = array('f')
        if row['dense']:
            dense.frombytes(row['dense'])
        row['dense_vector'] = dense
    return rows


def hybrid_search(
    dataset_id,
    query,
    project=None,
    sprint=None,
    limit=6,
    issue_keys=None,
    cache: RetrievalCache | None = None,
):
    meta = require_ready(dataset_id)['metadata']
    issues = analytics.select(store.summaries(dataset_id, project), sprint)
    allowed = {i['key']: i for i in issues if issue_keys is None or i['key'] in issue_keys}
    query_tokens = list(dict.fromkeys(tokens(query)))[:40]
    if not query_tokens or not allowed:
        return []
    scope_key = retrieval_cache.key(
        [
            dataset_id,
            meta['sha256'],
            meta['built_at'],
            meta.get('embedding_signature'),
            retrieval_cache.VERSION,
            project,
            sprint,
            sorted(allowed),
        ]
    )
    exact_key = retrieval_cache.key([scope_key, ' '.join(query.casefold().split()), limit])
    cached = cache.get('results', exact_key) if cache is not None else None
    if cached is not None:
        for item in cached:
            item['cache'] = 'exact retrieval hit'
        return cached
    dense_query = (
        (
            remote_embeddings([query], config=dataset_embedding_config(dataset_id), query=True, cache=cache)
            if cache is not None
            else remote_embeddings([query], config=dataset_embedding_config(dataset_id), query=True)
        )[0]
        if meta['embedding_provider'] != 'local'
        else None
    )
    guard_tokens = query_tokens + re.findall(r'\b\d+\b', query)
    pool = cache.semantic(scope_key, dense_query, guard_tokens) if cache is not None else None
    with vector_store.connect() as db:
        chunks = [
            c
            for c in cached_chunks(dataset_id, meta['built_at'])
            if c['issue_key'] in allowed and (not project or c['project'] == project)
        ]
        weights = {
            r['term']: r['idf']
            for r in db.execute(
                'SELECT term,idf FROM agent_terms WHERE dataset_id=? AND term IN ('
                + ','.join('?' for _ in query_tokens)
                + ')',
                [dataset_id, *query_tokens],
            )
        }
        fts = ' OR '.join('"' + t.replace('"', '""') + '"' for t in query_tokens)
        fsql = 'SELECT chunk_id FROM agent_fts JOIN agent_chunks ON agent_chunks.id=agent_fts.chunk_id WHERE agent_fts MATCH ? AND agent_fts.dataset_id=? AND agent_chunks.issue_key IN (SELECT value FROM json_each(?))'
        fargs = [fts, dataset_id, json.dumps(list(allowed))]
        if project:
            fsql += ' AND agent_fts.project=?'
            fargs.append(project)
        lexical = [r['chunk_id'] for r in db.execute(fsql + ' ORDER BY bm25(agent_fts) LIMIT 200', fargs)]
    qnorm = math.sqrt(sum(w * w for w in weights.values())) or 1
    scores = {}
    for c in chunks:
        if pool is not None and c['id'] not in pool and c['id'] not in lexical:
            continue
        if dense_query is not None:
            vector = c['dense_vector']
            if len(vector) != len(dense_query):
                raise RetrievalError('Embedding dimensions do not match this index. Rebuild it.')
            similarity = sum(x * y for x, y in zip(vector, dense_query))
        else:
            vector = c['sparse']
            similarity = sum(vector.get(t, 0) * w / qnorm for t, w in weights.items())
        if similarity > (
            meta.get(
                'similarity_floor',
                0.25 if meta.get('embedding_model', '').split(':')[0] == 'embeddinggemma' else 0.45,
            )
            if dense_query is not None
            else 0
        ):
            scores[c['id']] = similarity
    # Keep weak semantic overlap from gaining a second vote merely by matching
    # a generic keyword. Absolute floors still control no-match behavior.
    candidates = scores
    if dense_query is not None and scores:
        relative_floor = max(scores.values()) - 0.10
        candidates = {key: value for key, value in scores.items() if value >= relative_floor}
    ranked = sorted(candidates, key=lambda k: (-candidates[k], k))[:200]
    fused = defaultdict(float)
    for ranking in (ranked, lexical):
        for rank, ident in enumerate(ranking):
            fused[ident] += 1 / (60 + rank + 1)
    if cache is not None:
        cache.remember_pool(
            scope_key, query, dense_query, guard_tokens, sorted(fused, key=lambda k: -fused[k])[:200]
        )
    results = []
    for c, rank_score in rerank.rank(
        chunks, allowed, fused, scores, query, query_tokens, min(max(limit, 1), 200)
    ):
        ident = c['id']
        i = allowed[c['issue_key']]
        results.append(
            {
                **{k: i[k] for k in ('key', 'summary', 'project_key', 'status', 'type', 'priority')},
                'excerpt': c['content'][:1700],
                'chunk_id': c['id'],
                'score': round(fused[ident], 5),
                'rerank_score': rank_score,
                'cosine': round(scores.get(ident, 0), 4),
                'lexical_match': ident in lexical,
                'retrieval': ('semantic + keyword' if dense_query is not None else 'TF-IDF + keyword')
                + ' · reranked',
                'cache': 'semantic candidates reranked' if pool is not None else 'miss',
            }
        )
    if cache is not None:
        cache.put('results', exact_key, results)
    return results


def graph(dataset_id, reference='', keyword='', project=None, depth=2, limit=20):
    require_ready(dataset_id)
    issues = store.summaries(dataset_id, project)
    allowed = {i['key']: i for i in issues}
    with vector_store.connect() as db:
        nodes = {
            r['id']: dict(r)
            for r in db.execute('SELECT * FROM agent_nodes WHERE dataset_id=?', (dataset_id,))
            if not project or r['project'] == project
        }
        edges = [
            dict(r)
            for r in db.execute(
                'SELECT source,target,relation FROM agent_edges WHERE dataset_id=?', (dataset_id,)
            )
            if r['source'] in nodes and r['target'] in nodes
        ]
    if reference:
        starts = [reference] if reference in allowed else []
    else:
        terms = tokens(keyword)
        starts = [
            n['id']
            for n in nodes.values()
            if n['kind'] == 'topic' and terms and all(t in n['label'].lower() for t in terms)
        ][:8]
        starts += [
            r['key']
            for r in hybrid_search(dataset_id, keyword, project, limit=3)
            if r['lexical_match'] or r['cosine'] >= 0.65
        ]
    adjacency = defaultdict(list)
    for edge in edges:
        adjacency[edge['source']].append((edge['target'], edge, 'outgoing'))
        adjacency[edge['target']].append((edge['source'], edge, 'incoming'))
    queue = deque((s, 0, []) for s in dict.fromkeys(starts))
    seen, results = set(starts), []
    if not reference:
        results = [
            {
                **{k: allowed[s][k] for k in ('key', 'summary', 'status', 'type', 'project_key')},
                'path': [],
                'retrieval': 'keyword/vector seed',
            }
            for s in dict.fromkeys(starts)
            if s in allowed
        ]
    traversed = 0
    while queue and len(results) < limit and traversed < 400:
        node, distance, path = queue.popleft()
        if distance >= max(1, min(depth, 2)):
            continue
        for target, edge, direction in sorted(adjacency[node], key=lambda x: (x[0], x[1]['relation'])):
            if traversed >= 400:
                break
            traversed += 1
            if target in seen:
                continue
            seen.add(target)
            route = path + [{**edge, 'direction': direction}]
            queue.append((target, distance + 1, route))
            if target in allowed:
                i = allowed[target]
                results.append(
                    {
                        **{k: i[k] for k in ('key', 'summary', 'status', 'type', 'project_key')},
                        'path': route,
                        'retrieval': 'graph',
                    }
                )
                if len(results) >= limit:
                    break
    return {
        'seeds': [{'id': s, 'label': nodes[s]['label']} for s in dict.fromkeys(starts) if s in nodes],
        'tickets': results,
        'truncated': bool(queue) or traversed >= 400,
    }
