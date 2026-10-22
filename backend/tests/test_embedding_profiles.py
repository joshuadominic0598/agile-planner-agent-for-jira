"""Private model selection, exact chunk boundaries and rebuild isolation."""

import json

import httpx
import pytest
from app import store, vector_store
from app.agent import index
from app.agent.embedding_profiles import PROFILES, local_base, ticket_chunks
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    monkeypatch.setenv('JIRA_LOCAL_EMBEDDING_BASE_URL', 'http://127.0.0.1:11434/v1')
    with TestClient(app) as client:
        yield client


def upload(client, preset='lexical', prepare=True):
    csv = 'Issue key,Summary,Issue Type,Status,Description\nAPP-1,Login recovery,Story,To Do,Reset forgotten passwords securely\n'
    response = client.post(
        '/api/imports',
        files={'file': ('tickets.csv', csv)},
        data={'prepare_agent': str(prepare).lower(), 'embedding_preset': preset},
    )
    assert response.status_code == 202, response.text
    return response.json()['id']


@pytest.mark.parametrize('preset', ['small', 'large'])
@pytest.mark.parametrize(
    'text',
    [
        'x' * 19000,
        ('A meaningful paragraph about password recovery.\n\nNext sentence with context. ' * 230),
        '权限🔒कर्मचारी données ' * 1200,
    ],
)
def test_exact_cap_overlap_and_lossless_narrative(preset, text):
    profile = PROFILES[preset]
    title = 'A repeated title ' * 8
    result = list(
        ticket_chunks({'Description': text}, title, profile['chunk_characters'], profile['chunk_overlap'])
    )
    prefix = 'Title: ' + title[:160] + '\nDescription: '
    assert len(result) > 1
    assert all(chunk.startswith(prefix) and len(chunk) <= profile['chunk_characters'] for chunk in result)
    bodies = [chunk[len(prefix) :] for chunk in result]
    overlap = profile['chunk_overlap']
    assert all(a[-overlap:] == b[:overlap] for a, b in zip(bodies, bodies[1:]))
    assert bodies[0] + ''.join(body[overlap:] for body in bodies[1:]) == text


def test_short_narrative_has_one_chunk():
    assert list(ticket_chunks({'Description': 'short'}, 'Title', 1000, 200)) == [
        'Title: Title\nDescription: short'
    ]


@pytest.mark.parametrize('preset', ['small', 'large'])
def test_ticket_chunks_repeat_field_headers_and_preserve_every_field(preset):
    profile = PROFILES[preset]
    sections = {
        'Description': '权限🔒 données ' * 2400 + 'END_DESCRIPTION',
        'Acceptance criteria': 'Reject invalid records. ' * 500 + 'END_CRITERIA',
        'Comments': 'Custom field (Comments): ' + 'Resolution details. ' * 1300 + 'END_COMMENT',
        'Attachment references (contents unavailable)': 'design.pdf',
    }
    result = list(
        ticket_chunks(sections, 'Partner import', profile['chunk_characters'], profile['chunk_overlap'])
    )
    assert len(result) > 2
    assert all(len(chunk) <= profile['chunk_characters'] for chunk in result)
    assert all(chunk.startswith('Title: Partner import\n') for chunk in result)
    bodies = []
    for chunk in result:
        body = []
        for name in sections:
            assert f'\n{name}: ' in chunk
            value = chunk.split(f'\n{name}: ', 1)[1]
            later = list(sections)[list(sections).index(name) + 1 :]
            if later:
                value = value.split(f'\n{later[0]}: ', 1)[0]
            if value != '[no excerpt in this chunk]':
                body.append(value)
        bodies.append(''.join(body))
    overlap = profile['chunk_overlap']
    assert all(a[-overlap:] == b[:overlap] for a, b in zip(bodies, bodies[1:]))
    assert bodies[0] + ''.join(body[overlap:] for body in bodies[1:]) == ''.join(sections.values())


def test_all_fields_that_fit_remain_one_chunk_even_near_the_limit():
    sections = {
        'Description': 'd' * 750,
        'Acceptance criteria': 'a',
        'Comments': 'c',
        'Attachment references': 'f',
    }
    result = list(ticket_chunks(sections, 'Summary', 1000, 200))
    assert len(result) == 1
    assert len(result[0]) <= 1000
    assert '[no excerpt in this chunk]' not in result[0]


def test_small_tickets_stay_separate_without_padding_and_long_summary_is_preserved():
    first = list(ticket_chunks({'Description': 'first ticket only'}, 'First', 1000, 200))
    second = list(ticket_chunks({'Description': 'second ticket only'}, 'Second', 1000, 200))
    assert len(first) == len(second) == 1
    assert 'second ticket only' not in first[0] and 'first ticket only' not in second[0]
    title = 'Complete requirement ' * 30 + 'SUMMARY_END'
    result = list(ticket_chunks({'Description': ''}, title, 1000, 200))
    assert 'SUMMARY_END' in '\n'.join(result)


def test_full_custom_comments_are_embedded_and_never_mixed_between_tickets(client, monkeypatch):
    dataset = upload(client)
    record = store.issue(dataset, 'APP-1')
    description = 'Recovery requirements. ' * 1400 + 'DESCRIPTION_TAIL'
    comment = 'Custom resolution details. ' * 1000 + 'COMMENT_TAIL'
    record['details']['fields'].update(
        {
            'Description': [description],
            'Custom field (Acceptance Criteria)': ['CRITERIA_END'],
            'Custom field (Comments)': [comment, 'SECOND_COMMENT'],
            'Comments': ['PLURAL_COMMENT'],
        }
    )
    store.save_issues(dataset, [(record['summary'], record['details'])])
    original = httpx.Client
    embedded = []

    def handler(request):
        body = json.loads(request.content)
        embedded.extend(body['input'])
        return httpx.Response(200, json={'embeddings': [[1.0, 0.0] for _ in body['input']]})

    monkeypatch.setattr(
        index.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    assert (
        client.post(f'/api/datasets/{dataset}/agent/index', json={'embedding_preset': 'small'}).status_code
        == 202
    )
    assert index.status(dataset)['status'] == 'ready'
    body = '\n'.join(embedded)
    for marker in ('DESCRIPTION_TAIL', 'COMMENT_TAIL', 'SECOND_COMMENT', 'PLURAL_COMMENT', 'CRITERIA_END'):
        assert marker in body
    assert 'Custom field (Comments)' in body
    from app.agent.tools import Context

    packet = Context(dataset).get_ticket('APP-1')['ticket_context']
    assert packet['comments']['count'] == 3
    with vector_store.connect() as db:
        stored = db.execute('SELECT content FROM agent_chunks WHERE dataset_id=?', (dataset,)).fetchall()
    assert len(stored) == len(embedded)
    assert all(len(row['content']) <= 1000 for row in stored)
    assert all('Description: ' in row['content'] and 'Comments: ' in row['content'] for row in stored)


@pytest.mark.parametrize(
    'url',
    [
        'https://api.openai.com/v1',
        'http://192.168.1.1:11434',
        'http://localhost.evil.test',
        'http://user:secret@localhost',
        'http://localhost/v1?proxy=cloud',
    ],
)
def test_private_profiles_reject_remote_or_credential_urls(monkeypatch, url):
    monkeypatch.setenv('JIRA_LOCAL_EMBEDDING_BASE_URL', url)
    with pytest.raises(ValueError, match='local Ollama'):
        local_base()


def test_options_and_upload_choice_saved_without_indexing(client):
    options = client.get('/api/agent/embedding-options').json()['options']
    assert [option['id'] for option in options] == ['small', 'large']
    dataset = upload(client, 'large', prepare=False)
    status = client.get(f'/api/datasets/{dataset}/agent/status').json()
    assert status['status'] == 'missing'
    assert status['embedding']['preset'] == 'large'
    assert status['embedding']['model'] == 'qwen3-embedding:4b'
    assert status['embedding']['private_local'] is True
    assert store.dataset(dataset)['embedding_preset'] == 'large'
    assert (
        client.post(
            f'/api/datasets/{dataset}/agent/index', json={'embedding_preset': 'paid-model'}
        ).status_code
        == 422
    )


def test_model_switch_builds_and_queries_same_local_model_without_credentials(client, monkeypatch):
    first, other = upload(client), upload(client)
    store.mongo().issues.update_one(
        {'dataset_id': first},
        {'$set': {'details.fields.Description': ['Password recovery narrative. ' * 500]}},
    )
    # A legacy cloud key/provider must never leak into the explicit private choices.
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'openai')
    monkeypatch.setenv('OPENAI_API_KEY', 'private-test-key')
    original = httpx.Client
    requests = []

    def handler(request):
        assert str(request.url) == 'http://127.0.0.1:11434/api/embed'
        assert 'authorization' not in request.headers
        body = json.loads(request.content)
        assert body['truncate'] is False
        requests.append(body)
        size = 3 if body['model'] == 'embeddinggemma' else 4
        return httpx.Response(200, json={'embeddings': [[1.0] + [0.0] * (size - 1) for _ in body['input']]})

    monkeypatch.setattr(
        index.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    for preset in ['small', 'large']:
        response = client.post(f'/api/datasets/{first}/agent/index', json={'embedding_preset': preset})
        assert response.status_code == 202, response.text
        status = index.status(first)
        assert status['status'] == 'ready', status
        assert status['metadata']['embedding_preset'] == preset
        assert status['metadata']['chunk_characters'] == PROFILES[preset]['chunk_characters']
        assert status['metadata']['chunk_overlap'] == PROFILES[preset]['chunk_overlap']
        with vector_store.connect() as db:
            stored = [
                row[0] for row in db.execute('SELECT content FROM agent_chunks WHERE dataset_id=?', (first,))
            ]
        assert len(stored) > 1
        assert max(map(len, stored)) <= PROFILES[preset]['chunk_characters']
        assert index.hybrid_search(first, 'forgotten passwords')[0]['key'] == 'APP-1'
        assert requests[-1]['model'] == PROFILES[preset]['model']
        assert requests[-1]['input'][0].startswith(
            'task: search result' if preset == 'small' else 'Instruct:'
        )
        assert index.dataset_embedding_config(other)['preset'] == 'lexical'
    assert index.status(other)['status'] == 'ready'


def test_failed_local_rebuild_preserves_old_vectors_and_analytics_without_fallback(client, monkeypatch):
    dataset = upload(client)
    with vector_store.connect() as db:
        before = [
            tuple(row) for row in db.execute('SELECT * FROM agent_chunks WHERE dataset_id=?', (dataset,))
        ]
    original = httpx.Client
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(404, json={'error': 'model not found'})

    monkeypatch.setattr(
        index.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    assert (
        client.post(f'/api/datasets/{dataset}/agent/index', json={'embedding_preset': 'large'}).status_code
        == 202
    )
    state = index.status(dataset)
    assert state['status'] == 'failed'
    assert 'ollama pull qwen3-embedding:4b' in state['message']
    assert requests == ['http://127.0.0.1:11434/api/embed']
    assert store.dataset(dataset)['status'] == 'ready'
    with vector_store.connect() as db:
        assert [
            tuple(row) for row in db.execute('SELECT * FROM agent_chunks WHERE dataset_id=?', (dataset,))
        ] == before
    assert (
        client.post(f'/api/datasets/{dataset}/agent/index', json={'embedding_preset': 'lexical'}).status_code
        == 202
    )
    assert index.status(dataset)['status'] == 'ready'


def test_busy_build_cannot_change_saved_model(client):
    dataset = upload(client, prepare=False)
    assert index.reserve(dataset, 'small')
    response = client.post(f'/api/datasets/{dataset}/agent/index', json={'embedding_preset': 'large'})
    assert response.status_code == 409
    assert store.dataset(dataset)['embedding_preset'] == 'small'
