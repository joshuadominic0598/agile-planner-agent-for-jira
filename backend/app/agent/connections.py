"""Local workspace model profiles. Secrets are write-only and encrypted at rest."""

import os
import threading
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

from .. import store
from ..paths import data_dir
from .capabilities import api_protocol, legacy_chat_model
from .config import model_config

router = APIRouter(prefix='/api/agent/connections', tags=['Agent connections'])
KEY_LOCK = threading.Lock()
GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta/openai'
GEMINI_MODEL = 'gemini-3.5-flash-lite'


def cipher():
    from cryptography.fernet import Fernet

    path = data_dir() / '.agent-secret-key'
    with KEY_LOCK:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as handle:
                os.chmod(path, 0o600)
                handle.write(Fernet.generate_key())
        return Fernet(path.read_bytes())


def profiles():
    rows = store.mongo().agent_connections.find().sort('_id', 1)
    return [{**r['config'], 'id': r['id'], 'has_key': bool(r['secret'])} for r in rows]


def choices():
    cfg = model_config()
    result = [
        {
            'id': 'env:' + m,
            'name': m,
            'provider': cfg['provider'],
            'model': m,
            'web_available': cfg['web_available'],
        }
        for m in cfg['models']
        if cfg['configured']
    ]
    result += [
        {
            'id': p['id'],
            'name': p['name'] + ' · ' + p['model'],
            'provider': p['provider'],
            'model': p['model'],
            'web_available': p['provider'] == 'openai'
            and p['web_enabled']
            and api_protocol(p) == 'responses',
        }
        for p in profiles()
    ]
    from .context_budget import settings

    for option in result:
        resolved = (
            {**cfg, 'model': option['model']}
            if option['id'].startswith('env:')
            else next(p for p in profiles() if p['id'] == option['id'])
        )
        limits = settings(resolved)
        option.update(context_profile=limits['profile'], context_window=limits['window'])
    return result


def resolve(connection_id=None):
    cfg = model_config()
    if not connection_id:
        if cfg['configured']:
            return cfg
        available = profiles()
        if not available:
            return cfg
        connection_id = available[0]['id']
    if connection_id.startswith('env:'):
        model = connection_id[4:]
        if not cfg['configured'] or model not in cfg['models']:
            raise ValueError('This model is not configured. Choose a model from the selector.')
        return {**cfg, 'model': model, 'wire_model': cfg.get('model_aliases', {}).get(model, model)}
    row = store.mongo().agent_connections.find_one({'id': connection_id})
    if not row:
        raise ValueError('Connection not found. Choose another model or add a connection.')
    try:
        key = cipher().decrypt(row['secret'].encode()).decode() if row['secret'] else ''
    except Exception as exc:
        raise ValueError(
            'The saved key cannot be decrypted. Edit this connection and enter its API key again.'
        ) from exc
    data = row['config']
    return {
        'context_profile': 'auto',
        'context_window': 32768,
        'api_mode': 'auto',
        **data,
        'key': key,
        'configured': True,
        'web_available': data['provider'] == 'openai'
        and data['web_enabled']
        and api_protocol(data) == 'responses',
    }


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: Literal['compatible', 'openai', 'azure', 'gemini']
    model: str = Field(min_length=1, max_length=100)
    base: str = Field(default='', max_length=500)
    project_id: str = Field(default='', max_length=100)
    organization_id: str = Field(default='', max_length=100)
    api_key: SecretStr | None = None
    api_mode: Literal['auto', 'responses', 'chat'] = 'auto'
    web_enabled: bool = False
    reasoning_effort: Literal['', 'none', 'low', 'medium', 'high'] = ''
    context_profile: Literal['auto', 'compact', 'expanded'] = 'auto'
    context_window: int = Field(default=32768, ge=2048, le=262144)


def same_origin(request):
    origin = request.headers.get('origin')
    if origin and urlparse(origin).hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise HTTPException(403, 'Connection settings are available from the local app only.')


def save(profile, profile_id=None):
    from .provider import validate_base

    data = profile.model_dump(exclude={'api_key'})
    data = {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}
    if not data['name'] or not data['model']:
        raise HTTPException(422, 'Enter a connection name and model/deployment name.')
    if data['provider'] == 'openai' and any(char.isspace() for char in data['model']):
        raise HTTPException(422, 'Enter the exact OpenAI model ID without spaces, for example gpt-3.5-turbo.')
    data['base'] = (
        'https://api.openai.com/v1'
        if data['provider'] == 'openai'
        else GEMINI_BASE
        if data['provider'] == 'gemini'
        else data['base'].rstrip('/')
    )
    if api_protocol(data) == 'chat':
        data['web_enabled'] = False
    if legacy_chat_model(data):
        data['reasoning_effort'] = ''
    if data['provider'] == 'gemini':
        data['web_enabled'] = False
        data['project_id'] = data['organization_id'] = ''
        if data['reasoning_effort'] == 'none' and data['model'].startswith('gemini-3'):
            raise HTTPException(
                422,
                'Gemini 3 thinking cannot be disabled. Choose Model default or an available thinking level.',
            )
    try:
        validate_base(data['base'])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    parsed = urlparse(data['base'])
    if data['provider'] == 'azure':
        if (
            parsed.scheme != 'https'
            or not parsed.hostname
            or not parsed.hostname.endswith(
                ('.openai.azure.com', '.services.ai.azure.com', '.cognitiveservices.azure.com')
            )
        ):
            raise HTTPException(422, 'Use your HTTPS Azure OpenAI resource endpoint.')
        if parsed.path.rstrip('/') not in ('', '/openai/v1'):
            raise HTTPException(422, 'Use the Azure resource URL or its /openai/v1 base URL.')
        data['base'] = (
            data['base'] if parsed.path.rstrip('/') == '/openai/v1' else data['base'] + '/openai/v1'
        )
    if data['provider'] != 'compatible' and parsed.scheme != 'https':
        raise HTTPException(422, 'Hosted connections require HTTPS.')
    if any(
        '\n' in data[k] or '\r' in data[k] or not data[k].isascii() for k in ('project_id', 'organization_id')
    ):
        raise HTTPException(422, 'Project and organization IDs must be plain single-line identifiers.')
    previous = store.mongo().agent_connections.find_one({'id': profile_id}) if profile_id else None
    if profile_id and not previous:
        raise HTTPException(404, 'Connection not found.')
    if not profile_id and store.mongo().agent_connections.count_documents({}) >= 20:
        raise HTTPException(
            422, 'Up to 20 saved connections are supported. Edit or remove an existing connection.'
        )
    key = profile.api_key.get_secret_value().strip() if profile.api_key is not None else ''
    if len(key) > 4096 or '\r' in key or '\n' in key or not key.isascii():
        raise HTTPException(422, 'Enter a valid single-line API key.')
    if previous and previous['secret'] and not key:
        old = previous['config']
        if (old['provider'], old['base']) != (data['provider'], data['base']):
            raise HTTPException(422, 'Enter the API key again when changing its provider or endpoint.')
    if (
        (key or previous and previous['secret'])
        and parsed.scheme == 'http'
        and parsed.hostname not in {'localhost', '127.0.0.1', '::1', 'host.docker.internal'}
    ):
        raise HTTPException(422, 'Use HTTPS when sending API credentials to a remote server.')
    secret = cipher().encrypt(key.encode()).decode() if key else previous['secret'] if previous else ''
    if data['provider'] in {'openai', 'azure', 'gemini'} and not secret:
        raise HTTPException(422, 'Enter an API key for this hosted connection.')
    profile_id = profile_id or uuid.uuid4().hex
    store.mongo().agent_connections.replace_one(
        {'id': profile_id}, {'id': profile_id, 'config': data, 'secret': secret}, upsert=True
    )
    return next(p for p in profiles() if p['id'] == profile_id)


@router.get('')
def list_connections():
    return {
        'profiles': profiles(),
        'choices': choices(),
        'presets': [
            {
                'id': 'gemini-free-tier',
                'name': 'Gemini free-tier option',
                'provider': 'gemini',
                'model': GEMINI_MODEL,
                'base': GEMINI_BASE,
                'requires_key': True,
                'pricing_url': 'https://ai.google.dev/gemini-api/docs/pricing',
                'key_url': 'https://aistudio.google.com/api-keys',
            },
            {
                'id': 'nemotron-cascade-8b',
                'name': 'Nemotron Cascade 8B',
                'provider': 'compatible',
                'model': 'agileplanner-nemotron-cascade:8b',
                'base': 'http://'
                + ('host.docker.internal' if Path('/.dockerenv').exists() else '127.0.0.1')
                + ':11434/v1',
                'requires_key': False,
                'context_window': 32768,
            },
        ],
    }


@router.post('', status_code=201)
def create(profile: Profile, request: Request):
    same_origin(request)
    return save(profile)


@router.put('/{profile_id}')
def update(profile_id: str, profile: Profile, request: Request):
    same_origin(request)
    return save(profile, profile_id)


@router.delete('/{profile_id}')
def delete(profile_id: str, request: Request):
    same_origin(request)
    if not store.mongo().agent_connections.delete_one({'id': profile_id}).deleted_count:
        raise HTTPException(404, 'Connection not found.')
    return {'removed': True}


@router.post('/{connection_id}/test')
def test(connection_id: str, request: Request):
    same_origin(request)
    from . import provider

    class Probe:
        project = sprint = active_sprint = ''
        trace = []

        def call(self, name, args):
            self.trace.append({'tool': name, 'ok': True, 'result_count': 0})
            if name == 'calculator':
                from .tools import calculator

                return calculator(args.get('expression', '2+2'))
            return {
                'note': 'Connection test. No Jira data is sent. Use calculator with 2+2, then report the answer.'
            }

    try:
        cfg = resolve(connection_id)
        probe = Probe()
        answer, _ = provider.run(
            probe,
            'Connection test only: call calculator for 2+2, then reply with its answer in one sentence.',
            [],
            [],
            False,
            connection_id,
        )
        return {
            'ok': True,
            'model': cfg['model'],
            'tool_calling': bool(probe.trace),
            'message': 'Model responded and used tools.',
        }
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
