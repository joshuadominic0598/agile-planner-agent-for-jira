"""Refresh the versioned standard text-token catalog from official OpenAI pricing."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

url = 'https://developers.openai.com/api/docs/pricing'
text = urlopen(url + '.md').read().decode()
models = {}
for line in text.splitlines():
    if not line.startswith('| gpt-'):
        continue
    cells = [s.strip() for s in line.strip('|').split('|')]
    name = cells[0].split(' (')[0]
    if name in models or not re.fullmatch(r'gpt-[3456][\w.\-]*', name):
        continue
    try:
        rates = [float(c.replace('$', '').replace(',', '')) if c != '-' else None for c in cells[1:]]
    except ValueError:
        continue
    if len(rates) < 3:
        continue
    models[name] = {'input': rates[0], 'output': rates[1], 'cached_input': rates[2]}
    if len(rates) == 10:
        models[name].update(
            cache_write_30m=rates[3],
            cache_write_12h=rates[4],
            long_input=rates[5],
            long_output=rates[6],
            long_cached_input=rates[7],
            long_threshold=272000,
        )
for alias, target in {'gpt-4': 'gpt-4-0613', 'gpt-4-turbo': 'gpt-4-turbo-2024-04-09'}.items():
    if target in models:
        models[alias] = {**models[target], 'alias_of': target}
result = {
    'source': url,
    'checked_at': datetime.now(timezone.utc).isoformat(),
    'currency': 'USD',
    'unit': 'per million text tokens',
    'tier': 'standard',
    'models': models,
}
path = Path(__file__).resolve().parents[1] / 'backend/app/observability/model-pricing.json'
path.write_text(json.dumps(result, indent=2) + '\n')
print(f'Saved {len(models)} official model prices to {path}')
