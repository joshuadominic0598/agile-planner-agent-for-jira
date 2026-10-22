"""Versioned USD estimates; unknown rates remain unknown, never silently zero."""

import json
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads(Path(__file__).with_name('model-pricing.json').read_text())


def estimate(model, provider, usage, tier='default', overrides=None, base=''):
    rates = (overrides or {}).get(f'{provider}:{model}')
    source = 'workspace override' if rates else catalog()['source']
    if not rates and provider in {'openai', 'azure'}:
        name = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', model)
        rates = catalog()['models'].get(model) or catalog()['models'].get(name)
    from urllib.parse import urlparse

    if (
        not rates
        and provider == 'compatible'
        and urlparse(base).hostname in {'localhost', '127.0.0.1', 'host.docker.internal'}
    ):
        return {'usd': 0.0, 'basis': 'local inference; hardware/electricity excluded', 'priced': True}
    if not rates:
        return {'usd': None, 'basis': 'rate not configured', 'priced': False}
    inp, out = usage['input_tokens'], usage['output_tokens']
    cached = min(inp, usage.get('cached_input_tokens', 0))
    long = inp > rates.get('long_threshold', float('inf'))
    i = rates.get('long_input') if long else rates.get('input')
    o = rates.get('long_output') if long else rates.get('output')
    c = rates.get('long_cached_input') if long else rates.get('cached_input')
    c = i if c is None else c
    if i is None or o is None:
        return {'usd': None, 'basis': 'rate not configured for this context size', 'priced': False}
    multiplier = {
        'default': 1,
        'standard': 1,
        'auto': 1,
        'fast': 2,
        'priority': 2,
        'flex': 0.5,
        'batch': 0.5,
        'ultrafast': 6,
    }.get(tier)
    if multiplier is None:
        return {'usd': None, 'basis': 'unknown service tier', 'priced': False}
    return {
        'usd': round(((inp - cached) * i + cached * c + out * o) * multiplier / 1_000_000, 9),
        'basis': 'estimated text-token cost; excludes tax, region, tool fees and non-text tokens',
        'priced': True,
        'rates': rates,
        'source': source,
        'checked_at': catalog()['checked_at'],
        'tier': tier,
    }
