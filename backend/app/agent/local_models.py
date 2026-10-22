"""Explicit, resumable local model setup through Ollama's download API."""

import json
import threading
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from .. import store
from . import connections
from .embedding_profiles import local_base

router = APIRouter(prefix='/api/agent/local-models', tags=['Local models'])
LOCK = threading.Lock()
ACTIVE = ['queued', 'downloading', 'configuring', 'cancelling']
MODELS = {
    'qwen3-8b': {
        'name': 'Qwen 8B',
        'source': 'qwen3:8b',
        'model': 'agileplanner-qwen3:8b',
        'download': 'About 5.2 GB',
        'recommended': True,
        'license_url': 'https://huggingface.co/Qwen/Qwen3-8B/blob/main/LICENSE',
    },
    'nemotron-cascade-8b': {
        'name': 'Nemotron 8B',
        'source': 'hf.co/bartowski/nvidia_Nemotron-Cascade-8B-GGUF:Q4_K_M',
        'model': 'agileplanner-nemotron-cascade:8b',
        'download': 'About 5 GB',
        'recommended': False,
        'license_url': 'https://huggingface.co/nvidia/Nemotron-Cascade-8B',
    },
}


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize():
    db = store.mongo()
    db.agent_local_models.create_index('id', unique=True)
    db.agent_local_models.update_many(
        {'status': {'$in': ACTIVE}},
        {
            '$set': {
                'status': 'interrupted',
                'message': 'Setup stopped when the app restarted. Retry to resume cached downloads.',
                'updated_at': now(),
            }
        },
    )


def catalogue():
    base = local_base()
    available = set()
    reachable = False
    try:
        with httpx.Client(timeout=3, follow_redirects=False) as client:
            response = client.get(base + '/api/tags')
            response.raise_for_status()
            available = {model['name'] for model in response.json()['models']}
            reachable = True
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    rows = {row['id']: row for row in store.mongo().agent_local_models.find({}, {'_id': 0})}
    return {
        'ollama_available': reachable,
        'message': 'Ollama is ready.'
        if reachable
        else 'Install and start Ollama on this computer, then retry. Docker Desktop connects through host.docker.internal. No API key is needed.',
        'models': [
            {'id': ident, **model, 'installed': model['model'] in available, 'job': rows.get(ident)}
            for ident, model in MODELS.items()
        ],
    }


class Cancelled(Exception):
    pass


def install(ident, attempt, base):
    spec = MODELS[ident]
    query = {'id': ident, 'attempt': attempt}
    collection = store.mongo().agent_local_models

    def checkpoint():
        row = collection.find_one(query)
        if not row or row.get('cancel_requested'):
            raise Cancelled()

    def update(**values):
        checkpoint()
        collection.update_one(query, {'$set': {**values, 'updated_at': now()}})

    try:
        with httpx.Client(timeout=httpx.Timeout(90, connect=5), follow_redirects=False) as client:
            for endpoint, payload, status in (
                ('/api/pull', {'model': spec['source']}, 'downloading'),
                (
                    '/api/create',
                    {
                        'model': spec['model'],
                        'from': spec['source'],
                        'parameters': {
                            'num_ctx': 32768,
                            **({'temperature': 0.6, 'top_p': 0.95} if ident == 'nemotron-cascade-8b' else {}),
                        },
                    },
                    'configuring',
                ),
            ):
                update(
                    status=status,
                    message='Downloading model files'
                    if status == 'downloading'
                    else 'Configuring the 32K model window',
                )
                succeeded = False
                with client.stream('POST', base + endpoint, json={**payload, 'stream': True}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        checkpoint()
                        if not line.strip():
                            continue
                        packet = json.loads(line)
                        if packet.get('error'):
                            raise ValueError(
                                'Ollama could not prepare the model. Check disk space, registry access and model compatibility, then retry.'
                            )
                        values = {'message': str(packet.get('status', 'Working'))[:200]}
                        if packet.get('total'):
                            values.update(
                                completed=int(packet.get('completed', 0)), total=int(packet['total'])
                            )
                        update(**values)
                        succeeded |= packet.get('status') == 'success'
                if not succeeded:
                    raise ValueError('Model download ended before completion. Retry to resume cached files.')
            response = client.get(base + '/api/tags')
            response.raise_for_status()
            if spec['model'] not in {m['name'] for m in response.json()['models']}:
                raise ValueError('Ollama has not registered the model yet. Retry setup.')
        checkpoint()
        existing = next(
            (
                p
                for p in connections.profiles()
                if p['provider'] == 'compatible' and p['model'] == spec['model'] and p['base'] == base + '/v1'
            ),
            None,
        )
        profile = existing or connections.save(
            connections.Profile(
                name=spec['name'] + ' · local',
                provider='compatible',
                model=spec['model'],
                base=base + '/v1',
                api_mode='chat',
                context_window=32768,
            )
        )
        update(
            status='ready',
            connection_id=profile['id'],
            message='Downloaded and connected. Test tool calling or start chatting after preparing your ticket index.',
        )
    except Cancelled:
        collection.update_one(
            query,
            {
                '$set': {
                    'status': 'cancelled',
                    'message': 'Download stopped. Retry to resume cached files.',
                    'updated_at': now(),
                }
            },
        )
    except Exception as exc:
        message = (
            str(exc.detail)
            if isinstance(exc, HTTPException)
            else str(exc)
            if isinstance(exc, ValueError)
            else 'Local model setup failed. Start Ollama, check free disk space and network access, then retry. Cached downloads can resume.'
        )
        collection.update_one(
            query, {'$set': {'status': 'failed', 'message': message[:400], 'updated_at': now()}}
        )


@router.get('')
def list_models():
    return catalogue()


@router.post('/{ident}/install', status_code=202)
def start(ident: str, background: BackgroundTasks, request: Request):
    connections.same_origin(request)
    if ident not in MODELS:
        raise HTTPException(404, 'Choose a supported local model.')
    base = local_base()
    with LOCK:
        current = store.mongo().agent_local_models.find_one({'status': {'$in': ACTIVE}}, {'_id': 0})
        if current:
            if current['id'] == ident:
                return current
            raise HTTPException(409, 'Another model is downloading. Wait or cancel that download first.')
        if not catalogue()['ollama_available']:
            raise HTTPException(
                503,
                'Ollama is unavailable. Install and start Ollama on this computer, then retry. See ollama.com/download. Docker Desktop uses host.docker.internal:11434.',
            )
        row = {
            'id': ident,
            'attempt': uuid.uuid4().hex,
            'status': 'queued',
            'message': 'Preparing local model setup',
            'completed': 0,
            'total': 0,
            'updated_at': now(),
        }
        store.mongo().agent_local_models.replace_one({'id': ident}, row.copy(), upsert=True)
    background.add_task(install, ident, row['attempt'], base)
    return row


@router.post('/{ident}/cancel')
def cancel(ident: str, request: Request):
    connections.same_origin(request)
    result = store.mongo().agent_local_models.update_one(
        {'id': ident, 'status': {'$in': ACTIVE}},
        {
            '$set': {
                'cancel_requested': True,
                'status': 'cancelling',
                'message': 'Stopping download…',
                'updated_at': now(),
            }
        },
    )
    return {'saved': bool(result.matched_count)}
