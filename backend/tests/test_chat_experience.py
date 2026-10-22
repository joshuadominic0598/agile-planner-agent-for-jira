"""Chat correctness, retrieval adapter contracts and dependency boundaries."""

import ast
import csv
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.agent import index, topics
from app.agent.retrieval_cache import MemoryRetrievalCache
from app.agent.tools import Context
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    with TestClient(app) as client:
        yield client


def upload(client):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Issue key', 'Summary', 'Status', 'Status Category', 'Issue Type', 'Assignee', 'Description'])
    w.writerows(
        [
            [
                'APP-1',
                'Refresh token rotation',
                'Testing',
                'In Progress',
                'Story',
                'Ana',
                'Rotate OAuth refresh tokens',
            ],
            ['APP-2', 'Refresh token audit', 'Done', 'Done', 'Story', 'Ana', 'Audit token authentication'],
            [
                'APP-3',
                'Cache invalidation',
                'To Do',
                'To Do',
                'Story',
                'Bo',
                'Invalidate database cache entries',
            ],
            ['APP-4', 'Cache migration', 'To Do', 'To Do', 'Task', 'Bo', 'Cache database migration'],
        ]
    )
    return client.post(
        '/api/imports', files={'file': ('themes.csv', out.getvalue().encode(), 'text/csv')}
    ).json()['id']


def ask(client, dataset, message, session=None, **extra):
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': message, 'session_id': session, 'mode': 'retrieval', 'project': 'APP', **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_classification_preserves_backlog_collection_instead_of_listing_all_stories(client):
    dataset = upload(client)
    backlog = ask(client, dataset, 'Review the backlog')
    assert '| Total tickets | 3 |' in backlog['content'] and len(backlog['charts']) <= 1
    grouped = ask(
        client,
        dataset,
        'Classify the story tickets so I understand broadly what topics are covered',
        backlog['session_id'],
    )
    assert grouped['skill'] == 'topics' and '**2 tickets**' in grouped['content']
    assert 'APP-2' not in grouped['content'] and 'Matching tickets' not in grouped['content']
    assert grouped['conversation_context']['collection'] == 'backlog'
    assert grouped['charts'] == []
    all_stories = ask(
        client, dataset, 'Classify all project story tickets including completed', backlog['session_id']
    )
    assert (
        '**3 tickets**' in all_stories['content']
        and all_stories['conversation_context']['collection'] is None
    )


def test_topics_are_pure_reproducible_complete_partition():
    rows = [
        {
            'key': f'APP-{j}',
            'summary': 'OAuth authentication' if j < 8 else 'Database migrations',
            'description': 'Refresh token identity' if j < 8 else 'Schema indexes storage',
            'status': 'To Do',
        }
        for j in range(16)
    ]
    first = topics.group(rows)
    second = topics.group(list(reversed(rows)))
    assert first == second
    assigned = [key for theme in first['themes'] for key in theme['ticket_keys']]
    assert set(assigned) == {r['key'] for r in rows} and len(assigned) == len(rows)
    assert sum(t['count'] for t in first['themes']) == 16
    assert topics.group([])['total'] == 0
    with pytest.raises(ValueError, match='5,000'):
        topics.group(rows * 400)


def test_topic_correction_retains_subject_not_last_model_retrieved_ticket(client):
    from app.agent import conversation

    dataset = upload(client)
    ctx = Context(dataset)
    state = conversation.resolve(ctx, 'What is OAuth?')
    ctx.call('get_ticket', {'reference': 'APP-1'})
    assert state['tickets'] == []
    conversation.resolve(ctx, 'I think it is an authentication standard', state)
    assert 'OAuth' in ctx.topic_query and not ctx.context_lookup


@pytest.mark.parametrize('enabled', [False, True])
def test_cached_and_uncached_search_share_results_and_respect_metadata_scope(client, enabled):
    dataset = upload(client)
    cache = MemoryRetrievalCache() if enabled else None
    first = index.hybrid_search(dataset, 'refresh token', issue_keys={'APP-1'}, cache=cache)
    second = index.hybrid_search(dataset, 'refresh token', issue_keys={'APP-1'}, cache=cache)
    assert [i['key'] for i in first] == [i['key'] for i in second] == ['APP-1']
    assert all('rerank_score' in item for item in second)
    unrelated = index.hybrid_search(dataset, 'refresh token', issue_keys={'APP-3'}, cache=cache)
    assert unrelated == []
    ctx = Context(dataset, retrieval_cache=cache)
    a = ctx.call('search_tickets', {'query': 'refresh token', 'limit': 3})
    b = ctx.call('search_tickets', {'query': 'refresh token', 'limit': 3})
    assert a == b and ctx.trace[-1]['cached'] is True


def test_semantic_candidate_cache_reranks_and_never_crosses_literal_or_scope_guards(client, monkeypatch):
    dataset = upload(client)
    cache = MemoryRetrievalCache()
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_EMBEDDING_BASE_URL', 'http://local/v1')
    monkeypatch.setenv('JIRA_EMBEDDING_MODEL', 'embeddinggemma')
    monkeypatch.setattr(
        index, 'remote_embeddings', lambda texts, config=None, **kwargs: [[1.0, 0.0] for _ in texts]
    )
    index.reserve(dataset)
    index.build(dataset)
    first = index.hybrid_search(dataset, 'refresh token rotation', cache=cache)
    similar = index.hybrid_search(dataset, 'refresh token rotation please', cache=cache)
    assert first[0]['key'] == similar[0]['key'] == 'APP-1'
    assert all(i['cache'] == 'semantic candidates reranked' for i in similar)
    assert cache.semantic('other-scope', [1.0, 0.0], ['refresh', 'token']) is None
    cache.remember_pool('scope', 'phase 1', [1.0, 0.0], ['phase', '1'], ['a'])
    assert cache.semantic('scope', [1.0, 0.0], ['phase', '2']) is None
    cache.remember_pool('scope', 'approved', [1.0, 0.0], ['approved'], ['b'])
    assert cache.semantic('scope', [1.0, 0.0], ['not', 'approved']) is None
    assert (
        index.hybrid_search(dataset, 'refresh token rotation', cache=cache)[0]['cache']
        == 'exact retrieval hit'
    )


def test_cache_ttl_copy_isolation_bounds_and_concurrent_reads():
    now = [0.0]
    cache = MemoryRetrievalCache(clock=lambda: now[0], ttl=5)
    original = {'ids': ['APP-1']}
    cache.put('results', 'a', original)
    original['ids'].clear()
    with ThreadPoolExecutor(max_workers=8) as pool:
        reads = list(pool.map(lambda _: cache.get('results', 'a'), range(20)))
    assert all(r['ids'] == ['APP-1'] for r in reads)
    reads[0]['ids'].clear()
    assert cache.get('results', 'a')['ids'] == ['APP-1']
    for i in range(65):
        cache.put('results', str(i), {'number': i})
    assert cache.get('results', '0') is None
    now[0] = 6
    assert cache.get('results', '64') is None


def test_small_queries_have_no_charts_and_explicit_visuals_never_exceed_two(client):
    dataset = upload(client)
    first = ask(client, dataset, 'Tell me about Ana work items')
    follow = ask(client, dataset, 'Show their tickets', first['session_id'])
    assert not follow['charts'] and '### Status Category' not in follow['content']
    assert len(follow['content']) < 1400
    charts = ask(client, dataset, 'Give me a project overview with charts')
    assert len(charts['charts']) == 2 and '### Detailed Status' not in charts['content']
    assert '### Detailed Status' in charts['details_markdown']


def test_pure_core_dependency_boundaries():
    root = Path(__file__).parents[1] / 'app' / 'agent'
    allowed = {'collections', 'collections.abc', 'math', 're', 'typing'}
    for name in ('topics.py', 'rerank.py', 'ports.py', 'terminology.py'):
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names), (name, node.lineno)
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module in allowed, (name, node.lineno)


def test_specialized_acronym_does_not_invent_an_expansion_without_evidence(client, monkeypatch):
    from app.agent import terminology, transport

    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://model/v1')

    def unsupported(*args, **kwargs):
        return {
            'choices': [
                {
                    'message': {
                        'content': 'I cannot verify what XYZ means from this export. Which taxonomy do you mean?'
                    }
                }
            ]
        }

    monkeypatch.setattr(transport, 'request', unsupported)
    answer = ask(client, dataset, 'What is the XYZ taxonomy term?', mode='ai')
    assert answer['mode'] == 'ai' and 'cannot verify' in answer['content']
    assert not answer['charts'] and len(answer['content'].split()) < 80
    sources = [
        {
            'ticket': {'key': 'APP-1', 'summary': 'XYZ integration'},
            'source_text': 'XYZ stands for Example Taxonomy. More details.',
        }
    ]
    defined = terminology.evidence_answer('XYZ', sources, 'What does this taxonomy term mean?')
    assert 'Example Taxonomy' in defined and 'export' in defined and 'APP-1' in defined


def test_public_term_claim_without_web_citations_is_not_streamed(client, monkeypatch):
    import json

    import httpx
    from app.agent import provider

    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'openai')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setenv('JIRA_AI_WEB_ENABLED', 'true')
    original = httpx.Client

    def handler(request):
        body = (
            'data: '
            + json.dumps({'type': 'response.output_text.delta', 'delta': 'UNVERIFIED DOMAIN EXPANSION'})
            + '\n\n'
        )
        body += (
            'data: '
            + json.dumps(
                {
                    'type': 'response.completed',
                    'response': {
                        'output': [
                            {
                                'type': 'message',
                                'content': [{'type': 'output_text', 'text': 'UNVERIFIED DOMAIN EXPANSION'}],
                            }
                        ]
                    },
                }
            )
            + '\n\n'
        )
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=body)

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'What is the XYZ taxonomy term?', 'mode': 'ai', 'allow_web': True, 'stream': True},
    )
    assert 'UNVERIFIED DOMAIN EXPANSION' not in result.text
    events = [json.loads(line) for line in result.text.splitlines()]
    assert any(e['event'] == 'error' for e in events)
    assert not any(e['event'] == 'done' for e in events)
