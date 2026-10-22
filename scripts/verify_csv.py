"""Upload a real export to a running local app and check its derived snapshot.

Run with the development environment: PYTHONPATH=backend .venv/bin/python
scripts/verify_csv.py jiratickets.csv. No issue text is printed.
"""
import argparse
import json
import time
from pathlib import Path

import httpx

from app import analytics, importer, workflow

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('csv', type=Path)
parser.add_argument('--url', default='http://127.0.0.1:8000')
parser.add_argument('--check-id', help='Verify an existing snapshot, e.g. after restarting the app')
args = parser.parse_args()
content = args.csv.read_bytes()
parsed, metadata = importer.parse_csv(content)
records = [i for i, _ in parsed]

with httpx.Client(base_url=args.url, timeout=60) as client:
    if args.check_id:
        dataset_id = args.check_id
    else:
        response = client.post('/api/imports', files={'file': (args.csv.name, content, 'text/csv')})
        response.raise_for_status()
        dataset_id = response.json()['id']
    for _ in range(120):
        response = client.get(f'/api/imports/{dataset_id}')
        response.raise_for_status()
        job = response.json()
        if job['status'] in ('failed', 'ready'):
            break
        time.sleep(.25)
    assert job['status'] == 'ready', job['message']
    assert job['metadata']['sha256'] == metadata['sha256'], 'CSV fingerprint mismatch'
    response = client.get(f'/api/datasets/{dataset_id}/analytics')
    response.raise_for_status()
    actual = response.json()['overall']
    response = client.get(f'/api/datasets/{dataset_id}/projects')
    response.raise_for_status()
    projects = response.json()
    assert sum(p['count'] for p in projects) == len(records)
    configs = {}
    for project in projects:
        response = client.get(f'/api/datasets/{dataset_id}/workflow', params={'project': project['key']})
        response.raise_for_status()
        configs[project['key']] = response.json()
    assert actual == analytics.metrics(records), 'Metrics differ from the configured source export'
    category_counts = analytics.category_counts(records)
    assert sum(c['count'] for c in category_counts) == actual['total']
    for category in category_counts:
        response = client.get(f'/api/datasets/{dataset_id}/issues', params={'category_id': category['id'], 'page_size': 1})
        response.raise_for_status()
        assert response.json()['total'] == category['count'], 'Category count differs from issue filter'
    stages = workflow.stage_counts(records, configs)
    assert sum(s['count'] for s in stages) == actual['total']
    for stage in stages:
        response = client.get(f'/api/datasets/{dataset_id}/issues', params={'stage': stage['id'], 'page_size': 1})
        response.raise_for_status()
        assert response.json()['total'] == stage['count'], 'Stage count differs from issue filter'
    response = client.get(f'/api/datasets/{dataset_id}/issues/{records[0]["key"]}')
    response.raise_for_status()
    detail = response.json()
    assert detail['fields'] == parsed[0][1]['fields'], 'Exported field values differ'
    print(json.dumps({'dataset_id': dataset_id, 'projects': len(projects), 'metrics': actual, 'status_cards': len(stages), 'category_cards': {c['label']: c['count'] for c in category_counts}, 'column_occurrences_preserved': sum(len(v) for v in detail['fields'].values()), 'verified': True}, indent=2))
