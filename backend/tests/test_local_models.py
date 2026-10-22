"""Fresh-workspace downloads create local connections without credentials or Jira data."""

import json

import httpx
import pytest
from app import store
from app.agent import connections, local_models
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_LOCAL_EMBEDDING_BASE_URL', 'http://127.0.0.1:11434/v1')
    with TestClient(app) as client:
        yield client


def ollama(monkeypatch, fail=False, cancel=False):
    original = httpx.Client
    installed, requests = set(), []

    def handler(request):
        assert request.url.host == '127.0.0.1'
        assert 'authorization' not in request.headers
        body = json.loads(request.content) if request.content else None
        requests.append((request.url.path, body))
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': name} for name in installed]})
        if request.url.path == '/api/pull':
            if cancel:
                store.mongo().agent_local_models.update_one({}, {'$set': {'cancel_requested': True}})
            packets = [{'status': 'pulling file', 'completed': 4, 'total': 10}, {'status': 'success'}]
            if fail:
                packets = [{'error': 'private upstream error must not be echoed'}]
            return httpx.Response(200, text='\n'.join(json.dumps(p) for p in packets))
        assert request.url.path == '/api/create'
        assert body['parameters']['num_ctx'] == 32768
        assert body['stream'] is True
        installed.add(body['model'])
        return httpx.Response(200, text=json.dumps({'status': 'success'}))

    monkeypatch.setattr(
        local_models.httpx,
        'Client',
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    return requests


@pytest.mark.parametrize('ident', ['qwen3-8b', 'nemotron-cascade-8b'])
def test_install_connects_allowlisted_model_and_reuses_profile(client, monkeypatch, ident):
    requests = ollama(monkeypatch)
    options = client.get('/api/agent/local-models').json()
    assert options['ollama_available'] is True
    assert options['models'][0]['recommended'] is True
    assert connections.choices() == []
    result = client.post(f'/api/agent/local-models/{ident}/install')
    assert result.status_code == 202, result.text
    state = store.mongo().agent_local_models.find_one({'id': ident})
    assert state['status'] == 'ready', state
    profile = connections.resolve(state['connection_id'])
    assert profile['model'] == local_models.MODELS[ident]['model']
    assert profile['base'] == 'http://127.0.0.1:11434/v1'
    assert profile['key'] == '' and profile['context_window'] == 32768
    assert connections.choices()[0]['id'] == state['connection_id']
    assert client.post(f'/api/agent/local-models/{ident}/install').status_code == 202
    assert len(connections.profiles()) == 1
    assert all(not set(body or {}) & {'messages', 'input', 'api_key', 'key'} for _, body in requests)


def test_unavailable_service_and_unknown_models_are_actionable(client, monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(
        local_models.httpx,
        'Client',
        lambda **kwargs: original(transport=httpx.MockTransport(lambda r: httpx.Response(503)), **kwargs),
    )
    assert client.get('/api/agent/local-models').json()['ollama_available'] is False
    result = client.post('/api/agent/local-models/qwen3-8b/install')
    assert result.status_code == 503 and 'Ollama' in result.json()['detail']
    assert client.post('/api/agent/local-models/arbitrary-remote-model/install').status_code == 404
    assert not connections.choices()


@pytest.mark.parametrize('cancel', [False, True])
def test_failed_or_cancelled_setup_does_not_register_a_connection(client, monkeypatch, cancel):
    ollama(monkeypatch, fail=not cancel, cancel=cancel)
    assert client.post('/api/agent/local-models/qwen3-8b/install').status_code == 202
    state = store.mongo().agent_local_models.find_one({'id': 'qwen3-8b'})
    assert state['status'] == ('cancelled' if cancel else 'failed')
    assert 'private upstream' not in state['message']
    assert connections.choices() == []


def test_active_job_reuses_attempt_blocks_other_download_and_can_be_cancelled(client):
    store.mongo().agent_local_models.insert_one({'id': 'qwen3-8b', 'attempt': 'existing', 'status': 'queued'})
    result = client.post('/api/agent/local-models/qwen3-8b/install')
    assert result.status_code == 202 and result.json()['attempt'] == 'existing'
    assert client.post('/api/agent/local-models/nemotron-cascade-8b/install').status_code == 409
    assert client.post('/api/agent/local-models/qwen3-8b/cancel').json()['saved']
    assert store.mongo().agent_local_models.find_one({'id': 'qwen3-8b'})['status'] == 'cancelling'
    local_models.initialize()
    assert store.mongo().agent_local_models.find_one({'id': 'qwen3-8b'})['status'] == 'interrupted'


def test_cross_origin_download_is_rejected_before_any_model_call(client):
    result = client.post(
        '/api/agent/local-models/qwen3-8b/install', headers={'Origin': 'https://untrusted.invalid'}
    )
    assert result.status_code == 403
