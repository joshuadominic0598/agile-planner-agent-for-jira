import csv
import io
import json

import httpx
import pytest
from app import store, vector_store
from app.agent import index, provider, routes
from app.agent.tools import Context, calculator
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    with TestClient(app) as client:
        yield client


def upload(client, prepare=True):
    headers = [
        'Issue key',
        'Summary',
        'Issue Type',
        'Status',
        'Status Category',
        'Project key',
        'Description',
        'Assignee',
        'Reporter',
        'Sprint',
        'Sprint',
        'Parent',
        'Issue id',
        'Labels',
        'Component/s',
        'Comment',
        'Comment',
        'Outward issue link (Blocks)',
    ]
    rows = [
        [
            'APP-1',
            'Authentication platform',
            'Epic',
            'In Progress',
            'In Progress',
            'APP',
            'Build secure login',
            'Ana',
            'Lee',
            'Sprint 1',
            '',
            '',
            '1001',
            'identity',
            'Platform',
            'First note',
            'Acceptance requires audit',
            '',
        ],
        [
            'APP-2',
            'Rotate refresh tokens',
            'Story',
            'Testing',
            'In Progress',
            'APP',
            'OAuth refresh token rotation for authentication',
            'Ana',
            'Lee',
            'Sprint 2',
            'Sprint 2',
            '1',
            '1002',
            'identity',
            'API',
            'Old comment',
            'Second distinct comment',
            'APP-3',
        ],
        [
            'APP-3',
            'Improve login telemetry',
            'Task',
            'Done',
            'Done',
            'APP',
            'Capture login tracing',
            'Bo',
            'Ana',
            'Sprint 1',
            '',
            '1',
            '1003',
            'observability',
            'API',
            '',
            '',
            '',
        ],
        [
            'OTHER-2',
            'Private database migration',
            'Bug',
            'To Do',
            'To Do',
            'OTHER',
            'unrelated cassandra storage',
            'Cy',
            'Cy',
            'Other 1',
            '',
            '',
            '2002',
            'storage',
            'Database',
            '',
            '',
            '',
        ],
        [
            'APP-4',
            'Unscheduled unrelated issue',
            'Task',
            'To Do',
            'To Do',
            'APP',
            'Write documentation',
            '',
            '',
            '',
            '',
            '',
            '1004',
            '',
            'Docs',
            '',
            '',
            '',
        ],
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    result = client.post(
        '/api/imports',
        files={'file': ('agent.csv', output.getvalue().encode(), 'text/csv')},
        data={'prepare_agent': str(prepare).lower()},
    )
    assert result.status_code == 202
    return result.json()['id']


def test_index_repeated_fields_graph_and_scoped_retrieval(client):
    dataset = upload(client)
    status = index.status(dataset)
    assert status['status'] == 'ready', status
    assert status['metadata']['tickets'] == 5
    assert status['metadata']['edges'] >= 8
    with vector_store.connect() as db:
        content = '\n'.join(
            r[0]
            for r in db.execute(
                'SELECT content FROM agent_chunks WHERE dataset_id=? AND issue_key=?', (dataset, 'APP-2')
            )
        )
    assert 'Old comment' in content and 'Second distinct comment' in content
    assert 'assignee:' not in content and 'Sprint 2' not in content and 'APP-2' not in content
    assert Context(dataset).get_ticket('APP-2')['fields']['Comment'] == [
        'Old comment',
        'Second distinct comment',
    ]
    assert 'Sprint 2, Sprint 2' not in content
    assert index.hybrid_search(dataset, 'OAuth refresh rotation', 'APP')[0]['key'] == 'APP-2'
    assert index.hybrid_search(dataset, 'cassandra', 'APP') == []
    assert [r['key'] for r in index.hybrid_search(dataset, 'OAuth refresh rotation', 'APP', 'Sprint 2')] == [
        'APP-2'
    ]
    assert index.hybrid_search(dataset, 'OAuth refresh rotation', 'APP', '__unscheduled__') == []
    graph = index.graph(dataset, reference='APP-2', project='APP')
    assert {'APP-1', 'APP-3'} <= {i['key'] for i in graph['tickets']}
    assert 'OTHER-2' not in {i['key'] for i in graph['tickets']}
    assert any(any(p['relation'] == 'parent' for p in i['path']) for i in graph['tickets'])
    assert any(p['relation'] == 'Outward issue link (Blocks)' for i in graph['tickets'] for p in i['path'])
    topic = index.graph(dataset, keyword='identity', project='APP')
    assert any(s['label'] == 'Labels: identity' for s in topic['seeds'])
    assert 'APP-2' in {i['key'] for i in topic['tickets']}


def test_late_index_and_unavailable_then_chat_persistence(client):
    assert client.get('/api/datasets/missing/agent/status').status_code == 404
    dataset = upload(client, prepare=False)
    base = f'/api/datasets/{dataset}/agent'
    assert client.get(base + '/status').json()['status'] == 'missing'
    assert client.post(base + '/chat', json={'message': '2', 'mode': 'retrieval'}).status_code == 409
    assert client.post(base + '/index').status_code == 202
    assert client.get(base + '/status').json()['status'] == 'ready'
    ambiguous = client.post(base + '/chat', json={'message': '2', 'mode': 'retrieval'}).json()
    assert 'Which ticket' in ambiguous['content']
    assert 'APP-2' in ambiguous['content'] and 'OTHER-2' in ambiguous['content']
    result = client.post(
        base + '/chat', json={'message': 'Tell me about 2', 'project': 'APP', 'mode': 'retrieval'}
    ).json()
    assert result['mode'] == 'retrieval'
    assert 'Rotate refresh tokens' in result['content']
    assert {'APP-1', 'APP-2', 'APP-3'} <= {s['key'] for s in result['sources']}
    session = result['session_id']
    second = client.post(
        base + '/chat',
        json={
            'message': 'Summarize this sprint',
            'mode': 'retrieval',
            'project': 'APP',
            'sprint': 'Sprint 2',
            'active_sprint': 'Sprint 2',
            'session_id': session,
        },
    ).json()
    assert '| Total tickets | 1 |' in second['content']
    assert '| Distinct reporters | 1 |' in second['content']
    assert second['snapshot_metrics']
    assert (
        client.get(base + f'/sessions/{session}', params={'project': 'APP'}).json()['messages'][-1]['content']
        == second['content']
    )
    assert client.get(base + f'/sessions/{session}', params={'project': 'OTHER'}).status_code == 200
    assert (
        client.post(
            base + '/chat',
            json={'message': 'APP-1', 'project': 'OTHER', 'session_id': session, 'mode': 'retrieval'},
        ).status_code
        == 200
    )
    assert (
        client.post(
            base + '/chat',
            json={'message': 'attachment', 'project': 'APP', 'attachments': ['OTHER-2'], 'mode': 'retrieval'},
        ).status_code
        == 200
    )
    assert (
        client.post(
            base + '/chat',
            json={'message': 'attachment', 'project': 'APP', 'attachments': ['APP-1'], 'mode': 'retrieval'},
        ).status_code
        == 200
    )
    assert client.post(base + '/chat', json={'message': 'hello', 'mode': 'ai'}).status_code == 503
    assert client.post(base + '/chat', json={'message': '   '}).status_code == 422
    assert (
        client.post(
            base + '/chat',
            json={
                'message': 'Summarize this sprint',
                'project': 'APP',
                'sprint': 'Unknown',
                'mode': 'retrieval',
            },
        ).status_code
        == 200
    )


def test_summary_counts_and_exact_ids(client):
    dataset = upload(client)
    context = Context(dataset, 'APP', 'Sprint 2', 'Sprint 1')
    assert context.resolve('1002')['ticket']['key'] == 'APP-2'
    assert context.resolve('app-2')['ticket']['key'] == 'APP-2'
    summary = context.call('project_summary', {})
    assert summary['metrics']['total'] == 4
    assert summary['people'] == {'assignees': 2, 'reporters': 2}
    assert context.call('sprint_summary', {'sprint': None})['metrics']['total'] == 1
    assert context.call('sprint_summary', {'sprint': '__all__', 'project': 'APP'})['metrics']['total'] == 4
    assert 'error' in context.call('search_tickets', {'query': 'a', 'limit': 100})
    assert 'error' in context.call('execute_sql', {'sql': 'DROP TABLE issues'})
    assert 'error' in context.call('explore_graph', {'reference': None, 'keyword': 'identity', 'depth': 99})


@pytest.mark.parametrize(
    'expression',
    ['__import__("os").system("echo bad")', '2**1000', '1/0', 'float("inf")', '[1,2]', '9' * 300],
)
def test_calculator_rejects_code_or_unbounded_arithmetic(expression):
    with pytest.raises((ValueError, SyntaxError, ZeroDivisionError, OverflowError)):
        calculator(expression)


def test_calculator_and_restart_staleness(client, monkeypatch):
    assert calculator('(1749 / 2139) * 100')['result'] == pytest.approx(81.76718, abs=0.0001)
    dataset = upload(client)
    index.reserve(dataset)
    store.initialize()
    assert index.status(dataset)['status'] == 'failed'
    index.reserve(dataset)
    index.build(dataset)
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'compatible')
    assert index.status(dataset)['status'] == 'stale'
    index.reserve(dataset)
    index.build(dataset)
    assert index.status(dataset)['status'] == 'failed'
    assert store.dataset(dataset)['status'] == 'ready'


def fake_client(monkeypatch, replies):
    original = httpx.Client
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    return requests


def test_responses_agent_tool_loop_reasoning_and_actual_sources(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'openai')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-tool-model')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-secret')
    calls = fake_client(
        monkeypatch,
        [
            {
                'output': [
                    {'type': 'reasoning', 'id': 'r1', 'summary': []},
                    {
                        'type': 'function_call',
                        'name': 'get_ticket',
                        'arguments': '{"reference":"2"}',
                        'call_id': 'c1',
                    },
                ]
            },
            {
                'output': [
                    {
                        'type': 'function_call',
                        'name': 'explore_graph',
                        'arguments': '{"reference":"APP-2","keyword":null,"depth":2}',
                        'call_id': 'c2',
                    }
                ]
            },
            {
                'output': [
                    {
                        'type': 'message',
                        'role': 'assistant',
                        'content': [
                            {
                                'type': 'output_text',
                                'text': 'APP-2 needs testing; APP-1 is its parent.',
                                'annotations': [],
                            }
                        ],
                    }
                ]
            },
        ],
    )
    base = f'/api/datasets/{dataset}/agent'
    result = client.post(
        base + '/chat',
        json={'message': 'Analyze 2 and related work', 'project': 'APP', 'mode': 'ai', 'allow_web': True},
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['mode'] == 'ai'
    assert {'APP-1', 'APP-2', 'APP-3'} <= {s['key'] for s in data['sources']}
    assert calls[0]['store'] is False
    assert not any(t['type'] == 'web_search' for t in calls[0]['tools'])
    assert calls[1]['input'][-2]['type'] == 'function_call'
    assert any(i.get('type') == 'reasoning' for i in calls[1]['input'])
    assert 'OAuth refresh token' in calls[1]['input'][-1]['output']
    assert 'test-secret' not in result.text
    assert 'untrusted' in calls[0]['instructions']


def test_compatible_model_selects_evidence_tool_and_writes_sprint_answer(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-tools')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://localhost:11434/v1')
    calls = fake_client(
        monkeypatch,
        [
            {
                'choices': [
                    {
                        'message': {
                            'tool_calls': [
                                {
                                    'id': 'c1',
                                    'type': 'function',
                                    'function': {
                                        'name': 'sprint_summary',
                                        'arguments': '{"project":"APP","sprint":"Sprint 2"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {
                'choices': [
                    {
                        'message': {
                            'content': 'The sprint has one ticket in testing. Review its acceptance criteria before adding more work.'
                        }
                    }
                ]
            },
        ],
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'Summarize this sprint', 'project': 'APP', 'sprint': 'Sprint 2', 'mode': 'ai'},
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer['mode'] == 'ai' and answer['content'].startswith('The sprint has one ticket')
    assert '| Total tickets |' not in answer['content'] and answer['details_markdown'] == ''
    assert len(calls) == 2 and answer['charts'] == [] and answer['snapshot_metrics']
    assert any(t['function']['name'] == 'plan_investigation' for t in calls[0]['tools'])


def test_embedding_vectors_remote_adapter_and_failed_query(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_EMBEDDING_MODEL', 'test-embed')
    monkeypatch.setenv('JIRA_EMBEDDING_BASE_URL', 'http://localhost:11434/v1')
    original = httpx.Client

    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'data': [
                    {
                        'index': i,
                        'embedding': [1.0, 0.0] if 'OAuth' in text or 'secure' in text else [0.0, 1.0],
                    }
                    for i, text in enumerate(body['input'])
                ]
            },
        )

    monkeypatch.setattr(
        index.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    index.reserve(dataset)
    index.build(dataset)
    assert index.status(dataset)['status'] == 'ready'
    assert index.status(dataset)['metadata']['dimensions'] == 2
    result = index.hybrid_search(dataset, 'secure', 'APP')
    assert 'APP-2' in {r['key'] for r in result}
    assert result[0]['retrieval'] == 'semantic + keyword · reranked'
    monkeypatch.setattr(
        index,
        'remote_embeddings',
        lambda *args, **kwargs: (_ for _ in ()).throw(index.RetrievalError('Embedding connection failed.')),
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'find OAuth', 'project': 'APP', 'mode': 'retrieval'},
    )
    assert response.status_code == 200
    assert 'Embedding connection failed' in response.json()['content']


def test_provider_failure_does_not_save_fabricated_response(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://localhost:11434/v1')
    original = httpx.Client
    monkeypatch.setattr(
        provider.httpx,
        'Client',
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={'error': 'unauthorized'})
            ),
            **kwargs,
        ),
    )
    base = f'/api/datasets/{dataset}/agent'
    result = client.post(base + '/chat', json={'message': 'analyze project', 'project': 'APP', 'mode': 'ai'})
    assert result.status_code == 502
    assert store.mongo().agent_messages.count_documents({}) == 0


def test_exact_metadata_listing_for_sprint_themes_and_backlog(client):
    dataset = upload(client)
    context = Context(dataset, 'APP', 'Sprint 2')
    result = context.call(
        'list_tickets',
        {
            'sprint': None,
            'status': 'Testing',
            'priority': None,
            'issue_type': None,
            'assignee': None,
            'page': 1,
            'limit': 20,
        },
    )
    assert result['total'] == 1
    assert result['tickets'][0]['summary'] == 'Rotate refresh tokens'
    assert 'APP-2' in context.citations
    result = context.call('list_tickets', {'sprint': '__all__', 'project': 'APP', 'page': 1, 'limit': 2})
    assert result['total'] == 4 and result['has_more']
    assert (
        context.call('list_tickets', {'sprint': '__all__', 'project': 'APP', 'page': 2, 'limit': 2})[
            'has_more'
        ]
        is False
    )
    assert 'error' in context.call('list_tickets', {'page': 0})


def test_single_conversation_busy_and_dataset_isolation(client):
    first, second = upload(client), upload(client)
    base = f'/api/datasets/{first}/agent'
    session_id = client.post(
        base + '/chat', json={'message': '1', 'project': 'APP', 'mode': 'retrieval'}
    ).json()['session_id']
    assert (
        client.post(
            f'/api/datasets/{second}/agent/chat',
            json={'message': 'hello', 'project': 'APP', 'session_id': session_id, 'mode': 'retrieval'},
        ).status_code
        == 404
    )
    lock = routes.LOCKS[hash(session_id) % len(routes.LOCKS)]
    lock.acquire()
    try:
        assert (
            client.post(
                base + '/chat',
                json={'message': 'hello', 'project': 'APP', 'session_id': session_id, 'mode': 'retrieval'},
            ).status_code
            == 409
        )
    finally:
        lock.release()


def test_embedding_response_rejects_nonfinite_vectors(monkeypatch):
    config = {'provider': 'compatible', 'model': 'test', 'base': 'http://localhost/v1', 'key': ''}
    fake_client(monkeypatch, [{'data': [{'index': 0, 'embedding': ['nan', 1]}]}])
    with pytest.raises(index.RetrievalError):
        index.remote_embeddings(['hello'], config)


def test_openai_web_requires_both_server_and_request_optin(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'openai')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('OPENAI_API_KEY', 'test')
    monkeypatch.setenv('JIRA_AI_WEB_ENABLED', 'true')
    calls = fake_client(
        monkeypatch,
        [
            {
                'output': [
                    {'type': 'web_search_call', 'id': 'w1'},
                    {
                        'type': 'message',
                        'role': 'assistant',
                        'content': [
                            {
                                'type': 'output_text',
                                'text': 'See public docs.',
                                'annotations': [
                                    {
                                        'type': 'url_citation',
                                        'url': 'https://example.org/docs',
                                        'title': 'Public docs',
                                        'start_index': 4,
                                        'end_index': 15,
                                    }
                                ],
                            }
                        ],
                    },
                ]
            }
        ],
    )
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'Find public docs', 'mode': 'ai', 'allow_web': True},
    ).json()
    assert any(t['type'] == 'web_search' for t in calls[0]['tools'])
    assert result['web_sources'][0]['start_index'] == 4
    assert result['tools'][0]['tool'] == 'public_web_search'


def test_provider_rejects_malformed_payload_and_bounds_tool_loop(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://localhost:11434/v1')
    fake_client(monkeypatch, [{'choices': []}])
    base = f'/api/datasets/{dataset}/agent'
    assert client.post(base + '/chat', json={'message': 'analyze project', 'mode': 'ai'}).status_code == 502


def test_tool_loop_stops_without_final_answer(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'openai')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('OPENAI_API_KEY', 'test')
    calls = fake_client(
        monkeypatch,
        [
            {
                'output': [
                    {
                        'type': 'function_call',
                        'name': 'project_summary',
                        'arguments': '{}',
                        'call_id': f'c{i}',
                    }
                ]
            }
            for i in range(21)
        ],
    )
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat', json={'message': 'analyze project', 'mode': 'ai'}
    )
    assert result.status_code == 502
    assert len(calls) == 13
    assert calls[-1]['tool_choice'] == 'none'
    assert 'limit' in result.json()['detail']


def test_switching_allowed_environment_models_and_persisted_answer_model(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'qwen3:8b')
    monkeypatch.setenv('JIRA_AI_MODELS', 'qwen3:8b,qwen3:14b')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://localhost:11434/v1')
    monkeypatch.setenv('JIRA_AI_REASONING_EFFORT', 'medium')
    base = f'/api/datasets/{dataset}/agent'
    assert [c['model'] for c in client.get(base + '/status').json()['choices']] == ['qwen3:8b', 'qwen3:14b']
    calls = fake_client(
        monkeypatch,
        [
            {
                'choices': [
                    {
                        'message': {
                            'tool_calls': [
                                {
                                    'id': 'c1',
                                    'type': 'function',
                                    'function': {'name': 'project_summary', 'arguments': '{}'},
                                }
                            ]
                        }
                    }
                ]
            },
            {'choices': [{'message': {'content': 'Four project tickets.'}}]},
        ],
    )
    response = client.post(
        base + '/chat', json={'message': 'Overview', 'project': 'APP', 'connection_id': 'env:qwen3:14b'}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['model'] == 'qwen3:14b'
    assert all(c['model'] == 'qwen3:14b' for c in calls)
    assert calls[0]['reasoning_effort'] == 'medium'
    assert calls[0]['max_tokens'] >= 4096
    assert (
        client.post(
            base + '/chat', json={'message': 'Overview', 'connection_id': 'env:unapproved'}
        ).status_code
        == 422
    )
    history = client.get(base + f'/sessions/{result["session_id"]}', params={'project': 'APP'}).json()
    assert history['messages'][-1]['model'] == 'qwen3:14b'


def test_saved_gpt_credentials_encrypted_redacted_and_project_headers(client, monkeypatch):
    dataset = upload(client)
    profile = {
        'name': 'My GPT',
        'provider': 'openai',
        'model': 'test-gpt',
        'api_key': 'sk-test-private',
        'project_id': 'proj_example',
        'organization_id': 'org-example',
    }
    saved = client.post('/api/agent/connections', json=profile)
    assert saved.status_code == 201, saved.text
    assert 'sk-test-private' not in saved.text
    connection = saved.json()['id']
    assert saved.json()['has_key']
    assert 'sk-test-private' not in client.get('/api/agent/connections').text
    row = store.mongo().agent_connections.find_one({'id': connection})
    assert 'sk-test-private' not in row['secret'] and 'sk-test-private' not in row['config']
    from app.agent.connections import resolve

    assert resolve(connection)['key'] == 'sk-test-private'
    config = client.get(f'/api/datasets/{dataset}/agent/status').json()
    assert config['model']['available']
    assert config['choices'][0]['id'] == connection
    original = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    'output': [
                        {
                            'type': 'function_call',
                            'name': 'project_summary',
                            'arguments': '{}',
                            'call_id': 'c1',
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                'output': [
                    {
                        'type': 'message',
                        'content': [
                            {'type': 'output_text', 'text': 'Four project tickets.', 'annotations': []}
                        ],
                    }
                ]
            },
        )

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'Overview', 'project': 'APP', 'connection_id': connection},
    )
    assert response.status_code == 200, response.text
    assert requests[0].headers['OpenAI-Project'] == 'proj_example'
    assert requests[0].headers['OpenAI-Organization'] == 'org-example'
    assert requests[0].headers['Authorization'] == 'Bearer sk-test-private'
    assert 'sk-test-private' not in response.text
    assert (
        client.put(
            '/api/agent/connections/' + connection, json={**profile, 'name': 'Renamed', 'api_key': None}
        ).status_code
        == 200
    )
    assert resolve(connection)['key'] == 'sk-test-private'
    store.initialize()
    assert resolve(connection)['key'] == 'sk-test-private'
    assert client.delete('/api/agent/connections/' + connection).status_code == 200
    assert client.get('/api/agent/connections').json()['profiles'] == []


def test_azure_endpoint_deployment_and_credentials_test(client, monkeypatch):
    saved = client.post(
        '/api/agent/connections',
        json={
            'name': 'Azure project',
            'provider': 'azure',
            'model': 'my-deployment',
            'base': 'https://demo.openai.azure.com',
            'api_key': 'azure-test',
        },
    )
    assert saved.status_code == 201, saved.text
    profile = saved.json()
    assert profile['base'] == 'https://demo.openai.azure.com/openai/v1'
    calls = fake_client(
        monkeypatch,
        [
            {
                'output': [
                    {
                        'type': 'function_call',
                        'name': 'calculator',
                        'arguments': '{"expression":"2+2"}',
                        'call_id': 'c1',
                    }
                ]
            },
            {
                'output': [
                    {
                        'type': 'message',
                        'content': [{'type': 'output_text', 'text': 'The result is 4.', 'annotations': []}],
                    }
                ]
            },
        ],
    )
    response = client.post('/api/agent/connections/' + profile['id'] + '/test')
    assert response.status_code == 200, response.text
    assert response.json()['tool_calling']
    assert calls[0]['model'] == 'my-deployment'
    assert 'Jira' not in calls[0]['input'][-1]['content'] or 'No Jira' in calls[0]['input'][-1]['content']
    assert (
        client.put(
            '/api/agent/connections/' + profile['id'],
            json={
                'name': 'Moved',
                'provider': 'azure',
                'model': 'other',
                'base': 'https://other.openai.azure.com',
                'api_key': None,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            '/api/agent/connections',
            json={
                'name': 'Bad',
                'provider': 'azure',
                'model': 'x',
                'base': 'https://example.org',
                'api_key': 'test',
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            '/api/agent/connections',
            headers={'origin': 'https://evil.example'},
            json={'name': 'No', 'provider': 'openai', 'model': 'x', 'api_key': 'test'},
        ).status_code
        == 403
    )
    assert (
        client.post(
            '/api/agent/connections', json={'name': 'No key', 'provider': 'openai', 'model': 'x'}
        ).status_code
        == 422
    )


def test_response_budget_exhaustion_is_explicit(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://localhost:11434/v1')
    fake_client(
        monkeypatch, [{'choices': [{'finish_reason': 'length', 'message': {'content': 'incomplete'}}]}]
    )
    response = client.post(f'/api/datasets/{dataset}/agent/chat', json={'message': 'Overview'})
    assert response.status_code == 502
    assert 'budget' in response.json()['detail']


def test_connection_validation_does_not_echo_secret_in_error_response(client):
    response = client.post(
        '/api/agent/connections', json={'provider': 'openai', 'api_key': 'sk-never-echo-this'}
    )
    assert response.status_code == 422
    assert 'sk-never-echo-this' not in response.text


def test_gemini_preset_key_required_fixed_endpoint_and_tool_signatures(client, monkeypatch):
    dataset = upload(client)
    preset = client.get('/api/agent/connections').json()['presets'][0]
    assert preset['provider'] == 'gemini' and preset['requires_key']
    assert preset['model'] == 'gemini-3.5-flash-lite'
    profile = {
        'name': 'Gemini free-tier test',
        'provider': 'gemini',
        'model': preset['model'],
        'api_key': 'google-secret-test',
        'base': 'https://example.org/ignored',
        'project_id': 'proj_not_google',
        'organization_id': 'org_not_google',
        'web_enabled': True,
    }
    assert client.post('/api/agent/connections', json={**profile, 'api_key': None}).status_code == 422
    response = client.post('/api/agent/connections', json=profile)
    assert response.status_code == 201, response.text
    data = response.json()
    connection = data['id']
    assert data['base'] == 'https://generativelanguage.googleapis.com/v1beta/openai'
    assert data['project_id'] == data['organization_id'] == ''
    assert data['web_enabled'] is False
    assert 'google-secret-test' not in response.text
    original = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    'choices': [
                        {
                            'message': {
                                'role': 'assistant',
                                'content': None,
                                'extra_content': {
                                    'google': {'thought_signature': 'opaque-message-signature'}
                                },
                                'tool_calls': [
                                    {
                                        'id': 'c1',
                                        'type': 'function',
                                        'function': {
                                            'name': 'get_ticket',
                                            'arguments': '{"reference":"APP-2"}',
                                        },
                                        'extra_content': {
                                            'google': {'thought_signature': 'opaque-call-signature'}
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                'choices': [
                    {
                        'message': {
                            'role': 'assistant',
                            'content': 'APP-2 is Testing; it covers OAuth refresh token rotation.',
                        },
                        'finish_reason': 'stop',
                    }
                ]
            },
        )

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    answer = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'Explain APP-2', 'project': 'APP', 'connection_id': connection, 'mode': 'ai'},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()['model'] == preset['model']
    assert answer.json()['sources'][0]['key'] == 'APP-2'
    assert 'opaque-call-signature' not in answer.text
    assert 'google-secret-test' not in answer.text
    assert str(requests[0].url) == 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
    assert requests[0].headers['Authorization'] == 'Bearer google-secret-test'
    assert 'OpenAI-Project' not in requests[0].headers
    first, second = [json.loads(r.content) for r in requests]
    assert 'strict' not in first['tools'][0]['function']
    assert (
        second['messages'][-2]['tool_calls'][0]['extra_content']['google']['thought_signature']
        == 'opaque-call-signature'
    )
    assert (
        second['messages'][-2]['extra_content']['google']['thought_signature'] == 'opaque-message-signature'
    )
    assert second['messages'][-1]['role'] == 'tool'


def test_gemini_quota_error_does_not_retry_or_fallback(client, monkeypatch):
    dataset = upload(client)
    response = client.post(
        '/api/agent/connections',
        json={'name': 'Gemini', 'provider': 'gemini', 'model': 'gemini-3.5-flash-lite', 'api_key': 'test'},
    )
    connection = response.json()['id']
    original = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={'error': {'message': 'private quota payload should not be exposed'}})

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    answer = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'Project overview', 'project': 'APP', 'connection_id': connection},
    )
    assert answer.status_code == 502
    assert 'Gemini quota or rate limit' in answer.json()['detail']
    assert len(requests) == 1
    assert 'private quota payload' not in answer.text
    assert store.mongo().agent_messages.count_documents({}) == 0
    assert (
        client.post(
            '/api/agent/connections',
            json={
                'name': 'Gemini invalid thinking',
                'provider': 'gemini',
                'model': 'gemini-3.5-flash-lite',
                'api_key': 'test',
                'reasoning_effort': 'none',
            },
        ).status_code
        == 422
    )


def test_page_hint_is_not_query_boundary_and_people_use_metadata(client):
    dataset = upload(client)
    context = Context(dataset, 'OTHER', 'Other 1')
    context.chart_limit = 2
    assert context.get_ticket('APP-2')['ticket']['key'] == 'APP-2'
    all_work = context.call(
        'query_metadata',
        {
            'filters': [{'field': 'assignee', 'operator': 'contains', 'value': 'an'}],
            'group_by': 'status',
            'page': 1,
            'limit': 40,
        },
    )
    assert all_work['total'] == 2
    assert all_work['scope']['project'] == 'All projects'
    assert context.call('list_tickets', {})['total'] == 5
    assert context.call('list_tickets', {'project': '__current__'})['total'] == 1
    person = context.call('employee_analysis', {'person': 'Ana'})
    assert (
        person['assigned_tickets'] == 2
        and person['reported_tickets'] == 1
        and person['participation_unique'] == 3
    )
    assert person['metrics']['reporter_count'] == 1
    assert {s['key'] for s in context.citations.values()} >= {'APP-1', 'APP-2'}
    assert any(t['tool'] == 'calculator' for t in context.trace)
    assert context.visuals
    missing = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'tell me about taylor work item',
            'project': 'OTHER',
            'sprint': 'Other 1',
            'mode': 'retrieval',
        },
    ).json()
    assert 'No exported assignee or reporter matches' in missing['content']
    assert not missing['sources']
    assert not any(t['tool'] in {'search_tickets', 'explore_graph'} for t in missing['tools'])
    assigned = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'tell me about Ana work items', 'project': 'OTHER', 'mode': 'retrieval'},
    ).json()
    assert assigned['skill'] == 'employee'
    assert '| Assigned tickets | 2 |' in assigned['content']
    assert assigned['scope']['project'] == 'All projects'


def test_sprint_number_resolution_and_ambiguity_across_page_projects(client):
    dataset = upload(client)
    # Realistic exported names, different from the selected page's project/sprint.
    for key, name in [('APP-1', 'Example Sprint 43'), ('APP-2', 'Other team Sprint 43')]:
        store.mongo().issues.update_one(
            {'dataset_id': dataset, 'key': key}, {'$set': {'summary.sprints': [name]}}
        )
    context = Context(dataset, 'OTHER', 'Other 1')
    result = context.call('sprint_summary', {'sprint': '43'})
    assert result['ambiguous']
    assert len(result['candidates']) == 2
    result = context.call('sprint_summary', {'sprint': 'Example Sprint 43'})
    assert result['metrics']['total'] == 1
    assert result['scope']['project'] == 'All projects'
    assert result['scope']['sprint'] == 'Example Sprint 43'
    # Number 2 still resolves uniquely, across the current page boundary.
    dataset2 = upload(client)
    context = Context(dataset2, 'OTHER', 'Other 1')
    result = context.call('sprint_summary', {'sprint': '2'})
    assert result['metrics']['total'] == 1 and result['scope']['sprint'] == 'Sprint 2'
    assert context.call('sprint_summary', {'sprint': None})['scope']['sprint'] == 'Other 1'


def test_query_original_fields_and_backlog_proxy(client):
    dataset = upload(client)
    context = Context(dataset, 'APP')
    query = context.call(
        'query_metadata',
        {'filters': [{'field': 'Component/s', 'operator': 'eq', 'value': 'API'}], 'group_by': 'assignee'},
    )
    assert query['total'] == 2
    assert {i['name']: i['count'] for i in query['groups']} == {'Ana': 1, 'Bo': 1}
    backlog = context.call('backlog_overview', {})
    assert backlog['metrics']['total'] == 3
    assert backlog['unscheduled'] == 1
    assert 'not Jira board backlog' in backlog['definition']
    assert any(
        i['name'] == 'Unassigned share' and i['percent'] == 33.3 for i in backlog['calculated_insights']
    )


def test_streaming_events_and_persisted_activity_without_private_reasoning(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-tools')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://localhost:11434/v1')
    original = httpx.Client
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body['stream'] is True
        if len(requests) == 1:
            chunks = [
                {'choices': [{'delta': {'reasoning': 'PRIVATE REASONING MUST NOT APPEAR'}}]},
                {
                    'choices': [
                        {
                            'delta': {
                                'tool_calls': [
                                    {
                                        'index': 0,
                                        'id': 'c1',
                                        'type': 'function',
                                        'function': {'name': 'get_ticket', 'arguments': '{"reference":'},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    'choices': [
                        {
                            'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '"APP-2"}'}}]},
                            'finish_reason': 'tool_calls',
                        }
                    ]
                },
            ]
        else:
            chunks = [
                {'choices': [{'delta': {'content': '## Ticket\n\n**APP-2**'}}]},
                {'choices': [{'delta': {'content': ' is in Testing.'}, 'finish_reason': 'stop'}]},
            ]
        body = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=body)

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'Explain APP-2',
            'project': 'OTHER',
            'mode': 'ai',
            'stream': True,
            'page': 'overview',
        },
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert any(e['event'] == 'activity' and 'get ticket' in e.get('message', '') for e in events)
    deltas = [e['text'] for e in events if e['event'] == 'text_delta']
    assert len(deltas) == 2 and ''.join(deltas) == '## Ticket\n\n**APP-2** is in Testing.'
    final = next(e for e in events if e['event'] == 'done')
    assert final['page_hint']['project'] == 'OTHER'
    assert final['sources'][0]['key'] == 'APP-2'
    assert 'PRIVATE REASONING' not in response.text
    restored = client.get(
        f'/api/datasets/{dataset}/agent/sessions/{final["session_id"]}', params={'project': 'APP'}
    ).json()
    assert restored['messages'][-1]['content'] == final['content']
    assert restored['messages'][-1]['activity']


def test_responses_api_stream_and_midstream_errors(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'openai')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('OPENAI_API_KEY', 'test')
    original = httpx.Client
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            output = [
                {
                    'type': 'function_call',
                    'name': 'get_ticket',
                    'arguments': '{"reference":"APP-2"}',
                    'call_id': 'c1',
                }
            ]
            items = [{'type': 'response.completed', 'response': {'status': 'completed', 'output': output}}]
        else:
            items = [
                {'type': 'response.reasoning_summary_text.delta', 'delta': 'PRIVATE THINKING'},
                {'type': 'response.output_text.delta', 'delta': 'Ticket evidence.'},
                {
                    'type': 'response.completed',
                    'response': {
                        'status': 'completed',
                        'output': [
                            {
                                'type': 'message',
                                'content': [
                                    {'type': 'output_text', 'text': 'Ticket evidence.', 'annotations': []}
                                ],
                            }
                        ],
                    },
                },
            ]
        return httpx.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            content=''.join('data: ' + json.dumps(i) + '\n\n' for i in items),
        )

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat', json={'message': 'Explain APP-2', 'mode': 'ai', 'stream': True}
    )
    assert 'PRIVATE THINKING' not in result.text
    events = [json.loads(line) for line in result.text.splitlines()]
    assert next(e for e in events if e['event'] == 'done')['content'] == 'Ticket evidence.'

    # Broken stream is explicit and does not save a fabricated answer.
    def broken(request):
        return httpx.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            content='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
        )

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(broken), **kwargs)
    )
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat', json={'message': 'Explain APP-1', 'mode': 'ai', 'stream': True}
    )
    events = [json.loads(line) for line in result.text.splitlines()]
    assert any(e['event'] == 'error' for e in events) and not any(e['event'] == 'done' for e in events)


def test_legacy_think_blocks_are_not_streamed_as_answer_text():
    from app.agent.transport import VisibleText, clean_answer

    stream = VisibleText()
    assert stream.feed('<thi') == ''
    assert stream.feed('nk>PRIVATE INTERNAL') == ''
    assert stream.feed(' DETAILS</th') == ''
    assert stream.feed('ink>## Final answer') == '## Final answer'
    assert stream.feed('', final=True) == ''
    assert clean_answer('<think>private</think>Public answer') == 'Public answer'


def test_local_context_aliases_preserve_visible_model_choice(client, monkeypatch):
    from app.agent.connections import resolve

    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'qwen3:8b')
    monkeypatch.setenv('JIRA_AI_MODELS', 'qwen3:8b,qwen3:14b')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://localhost:11434/v1')
    monkeypatch.setenv(
        'JIRA_AI_MODEL_ALIASES', '{"qwen3:8b":"sprintlens-qwen3:8b","qwen3:14b":"sprintlens-qwen3:14b"}'
    )
    assert resolve('env:qwen3:14b')['model'] == 'qwen3:14b'
    assert resolve('env:qwen3:14b')['wire_model'] == 'sprintlens-qwen3:14b'
    dataset = upload(client)
    calls = fake_client(
        monkeypatch,
        [
            {
                'choices': [
                    {
                        'message': {
                            'tool_calls': [
                                {
                                    'id': 'c1',
                                    'function': {'name': 'get_ticket', 'arguments': '{"reference":"APP-2"}'},
                                }
                            ]
                        }
                    }
                ]
            },
            {'choices': [{'message': {'content': 'APP-2 is Testing.'}}]},
        ],
    )
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'Explain APP-2', 'connection_id': 'env:qwen3:14b'},
    ).json()
    assert calls[0]['model'] == 'sprintlens-qwen3:14b'
    assert result['model'] == 'qwen3:14b' and result['provider_model'] == 'sprintlens-qwen3:14b'


def test_stream_transport_preserves_opaque_signatures_and_sanitizes_json_fallback():
    from app.agent.transport import request

    events = []
    chunks = [
        {
            'choices': [
                {
                    'delta': {
                        'extra_content': {'google': {'thought_signature': 'opaque'}},
                        'tool_calls': [
                            {
                                'index': 0,
                                'id': 'c1',
                                'function': {'name': 'calculator', 'arguments': '{}'},
                                'extra_content': {'google': {'thought_signature': 'call-opaque'}},
                            }
                        ],
                    }
                }
            ]
        },
        {'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]},
    ]

    def handler(req):
        return httpx.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            content=''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = request(
            client, 'http://model/chat', {}, {}, 10, 'chat', lambda name, data: events.append((name, data))
        )
    message = result['choices'][0]['message']
    assert message['extra_content']['google']['thought_signature'] == 'opaque'
    assert message['tool_calls'][0]['extra_content']['google']['thought_signature'] == 'call-opaque'
    assert not any('opaque' in json.dumps(e) for e in events)

    def fallback(req):
        return httpx.Response(
            200, json={'choices': [{'message': {'content': '<think>private</think>Visible answer'}}]}
        )

    events = []
    with httpx.Client(transport=httpx.MockTransport(fallback)) as client:
        request(
            client, 'http://model/chat', {}, {}, 10, 'chat', lambda name, data: events.append((name, data))
        )
    assert ('text_delta', {'text': 'Visible answer'}) in events
    assert 'private' not in json.dumps(events)


def test_large_exported_fields_cannot_exhaust_ticket_tool_context(client):
    dataset = upload(client)
    record = store.issue(dataset, 'APP-2')
    details = record['details']
    details['fields'].update({f'Large custom field {n}': ['x' * 10000] * 5 for n in range(20)})
    store.save_issues(dataset, [(record['summary'], details)])
    result = Context(dataset).get_ticket('APP-2')
    assert result['fields_truncated'] is True
    assert sum(len(v) for values in result['fields'].values() for v in values) <= 12000
    assert 'Large custom field 19' in result['available_fields']
    # Complete originals remain queryable despite the model-context excerpt limit.
    result = Context(dataset).call(
        'query_metadata',
        {
            'filters': [{'field': 'key', 'operator': 'eq', 'value': 'APP-2'}],
            'group_by': 'Large custom field 19',
        },
    )
    assert result['total'] == 1 and result['groups'][0]['name'] == 'x' * 10000


def test_weak_semantic_overlap_does_not_get_a_double_ranking_vote(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_EMBEDDING_MODEL', 'embeddinggemma')
    monkeypatch.setenv('JIRA_EMBEDDING_BASE_URL', 'http://local/v1')

    def vectors(texts, config=None, query=False):
        return [[1.0, 0.0] if query or 'OAuth' in text else [0.3, (1 - 0.3**2) ** 0.5] for text in texts]

    monkeypatch.setattr(index, 'remote_embeddings', vectors)
    index.reserve(dataset)
    index.build(dataset)
    result = index.hybrid_search(dataset, 'Cleanup', 'APP')
    assert result[0]['key'] == 'APP-2' and result[0]['lexical_match'] is False


def test_no_report_text_streams_before_model_evidence_and_synthesis(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-tools')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://model/v1')
    calls = fake_client(
        monkeypatch,
        [
            {
                'choices': [
                    {
                        'message': {
                            'tool_calls': [
                                {
                                    'id': 'c1',
                                    'function': {'name': 'project_summary', 'arguments': '{"project":"APP"}'},
                                }
                            ]
                        }
                    }
                ]
            },
            {
                'choices': [
                    {
                        'message': {
                            'content': 'Focus on completing the authentication work before pulling another story.'
                        }
                    }
                ]
            },
        ],
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'Give me a project overview', 'project': 'APP', 'mode': 'ai', 'stream': True},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    deltas = [e['text'] for e in events if e['event'] == 'text_delta']
    final = next(e for e in events if e['event'] == 'done')
    assert deltas == [final['content']]
    assert final['content'].startswith('Focus on completing')
    assert final['details_markdown'] == '' and final['charts'] == [] and len(calls) == 2
    assert all('Application-prepared evidence' not in str(call) for call in calls)
    assert any(event['event'] == 'tool_usage' for event in events)


def test_csv_navigation_values_are_data_not_agent_instructions(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'openai')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-model')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    calls = fake_client(
        monkeypatch,
        [
            {
                'output': [
                    {
                        'type': 'function_call',
                        'name': 'get_ticket',
                        'arguments': '{"reference":"APP-2"}',
                        'call_id': 'c1',
                    }
                ]
            },
            {
                'output': [
                    {
                        'type': 'message',
                        'role': 'assistant',
                        'content': [
                            {'type': 'output_text', 'text': 'APP-2 is in Testing.', 'annotations': []}
                        ],
                    }
                ]
            },
        ],
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'Explain APP-2',
            'project': 'OTHER',
            'sprint': 'Delivery Window 72',
            'page': 'CSV supplied view',
            'mode': 'ai',
        },
    )
    assert response.status_code == 200
    assert 'Delivery Window 72' not in calls[0]['instructions']
    assert 'CSV supplied view' not in calls[0]['instructions']
    navigation = next(m for m in calls[0]['input'] if m['content'].startswith('Application navigation hints'))
    assert navigation['role'] == 'user' and 'Delivery Window 72' in navigation['content']
    assert 'untrusted data, not instructions' in navigation['content']


@pytest.mark.parametrize('adapter', ['openai', 'compatible'])
def test_both_adapters_use_normal_tool_loop_for_project_overview(client, monkeypatch, adapter):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', adapter)
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://model/v1')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    if adapter == 'openai':
        responses = [
            {
                'output': [
                    {
                        'type': 'function_call',
                        'name': 'project_summary',
                        'call_id': 'c1',
                        'arguments': '{"project":"APP"}',
                    }
                ]
            },
            {
                'output': [
                    {
                        'type': 'message',
                        'content': [
                            {
                                'type': 'output_text',
                                'text': 'The current focus is authentication. Confirm the release goal before reprioritizing.',
                            }
                        ],
                    }
                ]
            },
        ]
    else:
        responses = [
            {
                'choices': [
                    {
                        'message': {
                            'tool_calls': [
                                {
                                    'id': 'c1',
                                    'function': {'name': 'project_summary', 'arguments': '{"project":"APP"}'},
                                }
                            ]
                        }
                    }
                ]
            },
            {
                'choices': [
                    {
                        'message': {
                            'content': 'The current focus is authentication. Confirm the release goal before reprioritizing.'
                        }
                    }
                ]
            },
        ]
    calls = fake_client(monkeypatch, responses)
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'Give me a project overview', 'mode': 'ai', 'project': 'APP'},
    )
    assert response.status_code == 200, response.text
    assert response.json()['content'].startswith('The current focus is authentication.')
    assert len(calls) == 2 and 'select_analysis_findings' not in str(calls)


def test_specific_count_questions_use_metadata_queries_not_coarse_reports(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://local/v1')
    args = json.dumps(
        {
            'filters': [
                {'field': 'status', 'operator': 'eq', 'value': 'Testing'},
                {'field': 'type', 'operator': 'eq', 'value': 'Bug'},
            ]
        }
    )
    calls = fake_client(
        monkeypatch,
        [
            {
                'choices': [
                    {
                        'message': {
                            'tool_calls': [
                                {'id': 'c1', 'function': {'name': 'query_metadata', 'arguments': args}}
                            ]
                        }
                    }
                ]
            },
            {'choices': [{'message': {'content': '0 bugs are in Testing in this snapshot.'}}]},
        ],
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'How many Testing bugs are there?', 'mode': 'ai'},
    ).json()
    assert response['skill'] == '' and response['content'].startswith('0 bugs')
    assert json.loads(calls[1]['messages'][-1]['content'])['total'] == 0
    assert response['tools'][-1]['tool'] == 'query_metadata'


@pytest.mark.parametrize('adapter', ['compatible', 'openai'])
def test_missed_tool_call_retries_without_streaming_unverified_draft(client, monkeypatch, adapter):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', adapter)
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://local/v1')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    original = httpx.Client
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if adapter == 'compatible':
            message = (
                {'content': 'UNVERIFIED CLAIM'}
                if len(requests) == 1
                else {
                    'tool_calls': [
                        {
                            'id': 'c1',
                            'function': {
                                'name': 'query_metadata',
                                'arguments': '{"filters":[{"field":"status","operator":"eq","value":"Testing"}]}',
                            },
                        }
                    ]
                }
                if len(requests) == 2
                else {'content': 'One ticket is in Testing.'}
            )
            chunks = [
                {
                    'choices': [
                        {
                            'delta': message,
                            'finish_reason': 'tool_calls' if 'tool_calls' in message else 'stop',
                        }
                    ]
                }
            ]
        else:
            output = (
                [
                    {
                        'type': 'function_call',
                        'name': 'query_metadata',
                        'arguments': '{"filters":[{"field":"status","operator":"eq","value":"Testing"}]}',
                        'call_id': 'c1',
                    }
                ]
                if len(requests) == 2
                else [
                    {
                        'type': 'message',
                        'content': [
                            {
                                'type': 'output_text',
                                'text': 'UNVERIFIED CLAIM'
                                if len(requests) == 1
                                else 'One ticket is in Testing.',
                            }
                        ],
                    }
                ]
            )
            chunks = (
                [
                    {
                        'type': 'response.output_text.delta',
                        'delta': 'UNVERIFIED CLAIM' if len(requests) == 1 else 'One ticket is in Testing.',
                    }
                ]
                if len(requests) != 2
                else []
            )
            chunks += [{'type': 'response.completed', 'response': {'output': output}}]
        return httpx.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            content=''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks),
        )

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'How many tickets are Testing?', 'mode': 'ai', 'stream': True},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    final = next(e for e in events if e['event'] == 'done')
    assert final['content'] == 'One ticket is in Testing.' and final['mode'] == 'ai'
    assert 'UNVERIFIED CLAIM' not in response.text
    assert len(requests) == 3
    retry_tools = requests[1]['tools']
    assert all((t.get('function') or t)['name'] == 'plan_investigation' for t in retry_tools)
    assert any('Retrying once' in a['message'] for a in final['activity'])
    assert all('UNVERIFIED CLAIM' not in json.dumps(body) for body in requests)


@pytest.mark.parametrize('adapter', ['compatible', 'openai'])
def test_preloaded_reference_and_single_ticket_followup_need_no_duplicate_tool_call(
    client, monkeypatch, adapter
):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', adapter)
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://local/v1')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')

    def reply(text):
        return (
            {'choices': [{'message': {'content': text}}]}
            if adapter == 'compatible'
            else {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
        )

    requests = fake_client(monkeypatch, [reply('APP-2 is in Testing.'), reply('It is currently in Testing.')])
    base = f'/api/datasets/{dataset}/agent/chat'
    first = client.post(base, json={'message': 'Explain APP-2', 'mode': 'ai'}).json()
    assert first['content'] == 'APP-2 is in Testing.'
    assert first['sources'][0]['key'] == 'APP-2'
    second = client.post(
        base, json={'message': 'Explain that more briefly', 'mode': 'ai', 'session_id': first['session_id']}
    ).json()
    assert second['content'] == 'It is currently in Testing.' and second['sources'][0]['key'] == 'APP-2'
    assert len(requests) == 2
    for body in requests:
        inputs = body.get('input', body.get('messages'))
        evidence = next(m for m in inputs if m['content'].startswith('Application-retrieved ticket evidence'))
        assert 'OAuth refresh token rotation' in evidence['content']


def test_repeated_tool_skip_returns_error_without_template_or_saved_answer(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://local/v1')
    calls = fake_client(monkeypatch, [{'choices': [{'message': {'content': 'UNVERIFIED'}}]}] * 2)
    base = f'/api/datasets/{dataset}/agent'
    result = client.post(base + '/chat', json={'message': 'Find tickets about OAuth', 'mode': 'ai'})
    assert result.status_code == 502 and 'No automatic report' in result.json()['detail']
    assert 'UNVERIFIED' not in result.text and not client.get(base + '/sessions').json()['sessions']
    assert len(calls) == 2


def test_greetings_do_not_require_a_retrieval_tool(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://local/v1')
    calls = fake_client(
        monkeypatch, [{'choices': [{'message': {'content': 'Hello! Ask me about your Jira export.'}}]}]
    )
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat', json={'message': 'hello', 'mode': 'ai'}
    ).json()
    assert result['content'].startswith('Hello') and not result['tools']
    assert len(calls) == 1


@pytest.mark.parametrize('question', ['How many Testing bugs are there?', 'Find Taylor work items'])
def test_metadata_tool_skip_does_not_substitute_semantic_neighbors_or_project_totals(
    client, monkeypatch, question
):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://local/v1')
    calls = fake_client(monkeypatch, [{'choices': [{'message': {'content': 'UNVERIFIED'}}]}] * 2)
    result = client.post(f'/api/datasets/{dataset}/agent/chat', json={'message': question, 'mode': 'ai'})
    assert result.status_code == 502 and 'content' not in result.json() and len(calls) == 2


def test_twenty_native_actions_can_finish_with_bounded_context_and_no_orphan_outputs(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'openai')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    replies = [
        {
            'output': [
                {
                    'type': 'function_call',
                    'name': 'get_ticket',
                    'arguments': '{"reference":"APP-2"}',
                    'call_id': f'c{i}',
                }
            ]
        }
        for i in range(20)
    ]
    replies.append(
        {
            'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': 'APP-2 is in Testing.'}]}
            ]
        }
    )
    calls = fake_client(monkeypatch, replies)
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'effort': 'high', 'message': 'Inspect the relevant exported records', 'mode': 'ai'},
    )
    assert result.status_code == 200, result.text
    assert result.json()['content'] == 'APP-2 is in Testing.'
    assert len(calls) == 21 and calls[-1]['tools'] == [] and calls[-1]['tool_choice'] == 'none'
    for body in calls:
        ids = {item['call_id'] for item in body['input'] if item.get('type') == 'function_call'}
        assert all(
            item['call_id'] in ids for item in body['input'] if item.get('type') == 'function_call_output'
        )


@pytest.mark.parametrize(
    'hosted_provider,model,mode',
    [
        ('openai', 'gpt-3.5-turbo', 'auto'),
        ('openai', 'gpt-3.5-turbo-0125', 'auto'),
        ('azure', 'my-older-deployment', 'chat'),
    ],
)
def test_legacy_hosted_connections_use_chat_tool_loop_and_keep_project_headers(
    client, monkeypatch, hosted_provider, model, mode
):
    profile = {
        'name': 'Legacy test',
        'provider': hosted_provider,
        'model': model,
        'api_mode': mode,
        'api_key': 'synthetic-test-key',
        'project_id': 'proj_example',
        'reasoning_effort': '' if hosted_provider == 'azure' else 'high',
        'web_enabled': True,
        **({'base': 'https://example.openai.azure.com'} if hosted_provider == 'azure' else {}),
    }
    response = client.post('/api/agent/connections', json=profile)
    assert response.status_code == 201, response.text
    connection = response.json()
    assert not connection['web_enabled']
    if hosted_provider == 'openai':
        assert connection['context_window'] == 32768
        assert connection['reasoning_effort'] == ''
    requests = []
    original = httpx.Client

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.url.path.endswith('/chat/completions')
        assert body['model'] == model
        assert 'reasoning_effort' not in body
        assert (
            all('strict' not in tool['function'] for tool in body['tools'])
            if hosted_provider == 'openai'
            else True
        )
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    'choices': [
                        {
                            'message': {
                                'role': 'assistant',
                                'content': None,
                                'tool_calls': [
                                    {
                                        'id': 'calc',
                                        'type': 'function',
                                        'function': {
                                            'name': 'calculator',
                                            'arguments': '{"expression":"2+2"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200, json={'choices': [{'message': {'role': 'assistant', 'content': 'The result is 4.'}}]}
        )

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    result = client.post('/api/agent/connections/' + connection['id'] + '/test')
    assert result.status_code == 200, result.text
    assert result.json()['tool_calling']
    assert len(requests) == 2
    if hosted_provider == 'openai':
        assert requests[0].headers['OpenAI-Project'] == 'proj_example'
    assert 'synthetic-test-key' not in result.text


def test_openai_model_spaces_are_rejected_without_echoing_credentials(client):
    result = client.post(
        '/api/agent/connections',
        json={
            'name': 'Wrong model spelling',
            'provider': 'openai',
            'model': 'gpt 3.5 turbo',
            'api_key': 'synthetic-private-key',
        },
    )
    assert result.status_code == 422
    assert 'gpt-3.5-turbo' in result.json()['detail']
    assert 'synthetic-private-key' not in result.text


def test_explicit_model_context_window_is_authoritative():
    from app.agent.context_budget import settings

    result = settings({'model': 'gpt-3.5-turbo', 'context_window': 32768, 'context_profile': 'expanded'})
    assert result['window'] == 32768 and result['profile'] == 'expanded'
    assert result['ticket_max'] == 100
