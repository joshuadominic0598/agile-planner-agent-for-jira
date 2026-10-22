"""Check a persisted agent index against a supplied CSV; print aggregate evidence only."""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

import httpx

from app import importer

parser = argparse.ArgumentParser()
parser.add_argument('csv', type=Path)
parser.add_argument('--dataset', required=True)
parser.add_argument('--base-url', default='http://127.0.0.1:8000')
args = parser.parse_args()
rows, metadata = importer.parse_csv(args.csv.read_bytes())
issues = [i for i, _ in rows]
project = Counter(i['project_key'] for i in issues).most_common(1)[0][0]
selected = [i for i in issues if i['project_key'] == project]
base = f'{args.base_url}/api/datasets/{args.dataset}/agent'
with httpx.Client(timeout=120) as client:
    source = client.get(f'{args.base_url}/api/imports/{args.dataset}')
    source.raise_for_status()
    assert source.json()['metadata']['sha256'] == metadata['sha256']
    state = client.get(base+'/status'); state.raise_for_status()
    if state.json()['status'] != 'ready':
        client.post(base+'/index').raise_for_status()
        for attempt in range(120):
            state = client.get(base+'/status'); state.raise_for_status()
            if state.json()['status'] != 'building':
                break
            time.sleep(1)
    status = state.json()
    assert status['status'] == 'ready', status['message']
    assert status['metadata']['tickets'] == len(issues)
    sample = selected[0]
    def ask(message, **context):
        response = client.post(base+'/chat', json={'message':message,'project':project,'mode':'retrieval',**context})
        response.raise_for_status()
        return response.json()
    exact = ask(f"Tell me about {sample['key']}")
    assert sample['key'] in {s['key'] for s in exact['sources']}
    assert all(s['key'] in {i['key'] for i in issues} for s in exact['sources'])
    numeric = ask(sample['key'].rsplit('-',1)[-1])
    assert sample['key'] in numeric['content']
    summary = ask('Give me a project overview')
    assert f"| Total tickets | {len(selected):,} |" in summary['content']
    assert summary['snapshot_metrics']
    session = client.get(base+f"/sessions/{exact['session_id']}", params={'project':project})
    session.raise_for_status(); assert len(session.json()['messages']) == 2
    print(json.dumps({'index':status['status'],'tickets':status['metadata']['tickets'],'chunks':status['metadata']['chunks'],'nodes':status['metadata']['nodes'],'edges':status['metadata']['edges'],'embedding_mode':status['metadata']['embedding_provider'],'exact_reference':'passed','numeric_reference':'passed','project_scope':'passed','aggregate_total':'passed','conversation_persistence':'passed','ai_model_configured':status['model']['available']}, indent=2))
