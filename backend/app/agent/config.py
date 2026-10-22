import json
import os


def context_config():
    def mapping(name):
        try:
            value = json.loads(os.getenv(name, '{}') or '{}')
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}

    profiles = {
        k: v for k, v in mapping('JIRA_AI_MODEL_CONTEXT_PROFILES').items() if v in {'compact', 'expanded'}
    }
    windows = {
        k: v
        for k, v in mapping('JIRA_AI_MODEL_CONTEXT_WINDOWS').items()
        if type(v) is int and 2048 <= v <= 262144
    }
    return {
        'context_profile': 'auto',
        'context_window': 32768,
        'model_context_profiles': profiles,
        'model_context_windows': windows,
    }


def model_config():
    provider = os.getenv('JIRA_AI_PROVIDER', 'disabled').lower()
    key = os.getenv('JIRA_AI_API_KEY') or os.getenv('OPENAI_API_KEY', '')
    model = os.getenv('JIRA_AI_MODEL', '').strip()
    models = list(
        dict.fromkeys(m.strip() for m in [model, *os.getenv('JIRA_AI_MODELS', '').split(',')] if m.strip())
    )[:20]
    base = (
        'https://api.openai.com/v1' if provider == 'openai' else os.getenv('JIRA_AI_BASE_URL', '').rstrip('/')
    )
    try:
        aliases = json.loads(os.getenv('JIRA_AI_MODEL_ALIASES', '') or '{}')
        if not isinstance(aliases, dict):
            aliases = {}
        aliases = {
            k: v for k, v in aliases.items() if k in models and isinstance(v, str) and 0 < len(v) <= 150
        }
    except (ValueError, TypeError):
        aliases = {}
    configured = (
        provider in {'openai', 'compatible'}
        and bool(model and base)
        and (bool(key) or provider == 'compatible')
    )
    return {
        **context_config(),
        'provider': provider,
        'key': key,
        'model': model,
        'wire_model': aliases.get(model, model) if provider == 'compatible' else model,
        'model_aliases': aliases,
        'models': models,
        'reasoning_effort': os.getenv('JIRA_AI_REASONING_EFFORT', ''),
        'project_id': os.getenv('JIRA_AI_PROJECT_ID', ''),
        'organization_id': os.getenv('JIRA_AI_ORGANIZATION_ID', ''),
        'base': base,
        'configured': configured,
        'web_available': provider == 'openai'
        and configured
        and os.getenv('JIRA_AI_WEB_ENABLED', 'false').lower() == 'true',
    }


def embedding_signature(signature):
    # Host and container aliases refer to the same local embedding service.
    import re

    return re.sub(
        r'(?<=://)(?:host\.docker\.internal|localhost|127\.0\.0\.1)(?=[:/]|$)', 'local-host', signature
    )


def embedding_config():
    provider = os.getenv('JIRA_EMBEDDING_PROVIDER', 'local').lower()
    model = os.getenv(
        'JIRA_EMBEDDING_MODEL', 'text-embedding-3-small' if provider == 'openai' else ''
    ).strip()
    base = (
        'https://api.openai.com/v1'
        if provider == 'openai'
        else os.getenv('JIRA_EMBEDDING_BASE_URL', '').rstrip('/')
    )
    key = os.getenv('JIRA_EMBEDDING_API_KEY') or os.getenv('OPENAI_API_KEY', '')
    return {
        'provider': provider,
        'model': model,
        'base': base,
        'key': key,
        'signature': embedding_signature(f'{provider}:{model}:{base}')
        if provider != 'local'
        else 'local:tfidf-v1',
    }
