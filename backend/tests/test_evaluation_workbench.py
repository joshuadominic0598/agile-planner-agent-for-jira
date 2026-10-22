import csv
import io
import json
import uuid
from pathlib import Path

import httpx
import pytest
from app import store
from app.agent import project_context, prompt_versions
from app.observability import evaluation_datasets as golden
from app.observability import evaluation_jobs as jobs
from app.observability.dashboard import app
from app.observability.evaluation_import import parse_csv
from app.observability.reference_metrics import overlap
from fastapi.testclient import TestClient
from test_conversations import client as context_client
from test_operations import sample

client = context_client


def test_version_edits_are_immutable_and_human_review_publishes_a_new_version(client):
    source = sample(client)
    with TestClient(app) as ops:
        body = {
            'name': 'Cache golden set',
            'ticket_dataset_id': source,
            'cases': [
                {'id': 'cache', 'question': 'What does APP-1 do?', 'reference': 'It repairs cache refresh.'}
            ],
        }
        v1 = ops.post('/api/ops/evaluation/datasets', json=body).json()
        body.update(base_version_id=v1['id'], change_note='Clarify expected behavior')
        body['cases'][0]['reference'] = 'It retries a failed cache refresh.'
        v2 = ops.post(f'/api/ops/evaluation/datasets/{v1["dataset_id"]}/versions', json=body).json()
        assert v2['number'] == 2
        assert golden.version(v1['id'])['cases'][0]['reference'] == 'It repairs cache refresh.'
        assert (
            ops.post(f'/api/ops/evaluation/datasets/{v1["dataset_id"]}/versions', json=body).status_code
            == 409
        )
        store.mongo().agent_evaluations.insert_one(
            {'id': 'run', 'golden_dataset_id': v1['dataset_id'], 'golden_version_id': v2['id']}
        )
        store.mongo().agent_eval_results.insert_one(
            {
                'id': 'answer',
                'evaluation_id': 'run',
                'case_id': 'cache',
                'golden_version_id': v2['id'],
                'reference': body['cases'][0]['reference'],
                'status': 'success',
            }
        )
        response = ops.post(
            '/api/ops/evaluation/results/answer/review',
            json={
                'score': 4,
                'reference_verified': True,
                'corrected_reference': 'It retries upstream timeouts safely.',
            },
        )
        assert response.status_code == 200 and response.json()['new_version_number'] == 3
        assert (
            store.mongo().agent_eval_results.find_one({'id': 'answer'})['reference']
            == body['cases'][0]['reference']
        )
        history = ops.get(f'/api/ops/evaluation/datasets/{v1["dataset_id"]}/versions').json()
        assert [v['number'] for v in history] == [3, 2, 1]
        assert (
            golden.version(history[0]['id'])['cases'][0]['original_reference'] == 'It repairs cache refresh.'
        )


def test_demo_benchmark_and_legacy_conversation_keep_evidence_provenance(client):
    store.mongo().agent_eval_cases.insert_one(
        {
            'id': 'legacy-case',
            'dataset_version': 'a' * 64,
            'case_number': 1,
            'question': 'Who handles cache issues?',
            'reference': 'Ana handles them.',
            'original_reference': 'Ana handles them.',
            'reference_status': 'needs_human_verification',
            'source': {'file': 'Conversation.docx'},
            'expected': {'ticket_keys': [], 'clarification': False},
        }
    )
    store.mongo().agent_eval_results.insert_one(
        {
            'id': 'old-answer',
            'case_id': 'legacy-case',
            'run_id': 'trace',
            'retrieved_contexts': ['APP-1 | Assignee: Ana | Cache refresh'],
        }
    )
    golden.catalog()
    old = store.mongo().agent_eval_datasets.find_one({'id': 'conversation-' + 'a' * 24})
    case = golden.version(old['head_version_id'])['cases'][0]
    assert case['reference_contexts'] and case['context_status'] == 'needs_human_verification'
    assert 'trace' in case['context_source']
    demo = golden.version(golden.dataset('agileplanner-demo-golden')['head_version_id'])
    assert len(demo['cases']) == 10 and all(c['reference_contexts'] for c in demo['cases'])
    assert all(c['context_status'] == 'verified' for c in demo['cases'])
    assert demo['cases'][-1]['expected']['clarification']
    data = list(csv.reader(Path('resources/demo/agileplanner-demo.csv').open()))
    status_index = data[0].index('Status Category')
    assert sum(row[status_index] == 'Done' for row in data[1:]) == 18
    assert '100 tickets' in demo['cases'][0]['reference']
    assert demo['cases'][8]['expected']['ticket_keys'] == ['DEMO-85', 'DEMO-90', 'DEMO-95', 'DEMO-100']


def test_csv_contract_supports_golden_evidence_and_recorded_outputs(client):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            'question',
            'reference_answer',
            'reference_contexts',
            'answer',
            'retrieved_contexts',
            'conversation_id',
        ]
    )
    writer.writerow(
        [
            'What does this do?',
            'It repairs cache refresh.',
            json.dumps(['APP-1 cache requirements']),
            'It repairs cache refresh.',
            json.dumps(['APP-1 cache requirements']),
            'cache',
        ]
    )
    with TestClient(app) as ops:
        response = ops.post(
            '/api/ops/evaluation/import', files={'file': ('gold.csv', out.getvalue().encode(), 'text/csv')}
        )
        assert response.status_code == 201, response.text
        case = response.json()['cases'][0]
        assert case['reference_contexts'] == ['APP-1 cache requirements']
        assert case['provided_contexts'] == ['APP-1 cache requirements']
        assert case['provided_answer'] == case['reference']
        assert case['context_status'] == 'needs_human_verification'
        assert ops.get('/api/ops/evaluation/template.csv').status_code == 200
    simple = parse_csv(b'question,answer,retrieved_contexts\nWhat?,Cache repair,APP-1 requirements\n')[0]
    assert simple.reference == 'Cache repair' and simple.reference_contexts == ['APP-1 requirements']
    assert simple.provided_answer is None
    for malformed in [
        b'question\nHello\n',
        b'question,answer\nHello,Answer,Unexpected\n',
        b'question,question,answer\nq,q,a\n',
    ]:
        with pytest.raises(ValueError):
            parse_csv(malformed)


def test_ngram_metrics_have_expected_boundaries_and_short_orders_are_not_applicable():
    same = overlap('one two three four five six', 'ONE two three four five six')
    assert all(v == pytest.approx(1) for v in same['bleu'].values())
    assert all(v['f1'] == pytest.approx(1) for v in same['rouge'].values())
    assert same['rouge_l']['f1'] == 1
    different = overlap('one two three four five', 'six seven eight nine ten')
    assert different['bleu']['5'] == 0 and different['rouge']['2']['f1'] == 0
    short = overlap('hello world', 'hello world')
    assert short['bleu']['2'] == 1 and short['bleu']['3'] is None and short['rouge']['5'] is None


def test_two_model_job_uses_frozen_cases_and_separate_conversation_memory(client, monkeypatch):
    source = sample(client)
    project_context.write(source, '', 'Shared guidance before evaluation')
    pinned = prompt_versions.get(source)
    cases = [
        golden.GoldenCase(
            id=str(i),
            question=f'Cache question {i}',
            reference='Cache repair is safe.',
            conversation_id='cache' if i != 2 else 'other',
        )
        for i in range(4)
    ]
    v = golden.create(golden.DatasetWrite(name='Smoke tests', ticket_dataset_id=source, cases=cases))
    monkeypatch.setattr(
        jobs.connections,
        'resolve',
        lambda ident: {
            'provider': 'openai',
            'model': ident,
            'base': 'https://example.invalid',
            'key': 'not-a-key',
        },
    )
    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            return httpx.Response(200, json={'status': 'ready'}, request=httpx.Request('GET', url))

        def post(self, url, json):
            calls.append(dict(json))
            if len(calls) == 1:
                project_context.write(source, '', 'Changed during evaluation')
            run_id = uuid.uuid4().hex
            store.mongo().agent_runs.insert_one(
                {
                    'id': run_id,
                    'latency_ms': 123,
                    'model_call_count': 3,
                    'tool_call_count': 2,
                    'retrieved_contexts': ['Cache repair requirements.'],
                }
            )
            answer = {
                'event': 'done',
                'content': 'Cache repair is safe.',
                'session_id': json.get('session_id') or uuid.uuid4().hex,
                'run_id': run_id,
                'sources': [],
            }
            return httpx.Response(
                200, text=__import__('json').dumps(answer), request=httpx.Request('POST', url)
            )

    monkeypatch.setattr(jobs.httpx, 'Client', FakeClient)
    job = jobs.launch(
        jobs.Launch(
            golden_dataset_id=v['dataset_id'],
            version_id=v['id'],
            ticket_dataset_id=source,
            connection_ids=['model-a', 'model-b'],
            ragas=False,
            delay=0,
        ),
        spawn=False,
    )
    jobs.execute(job['id'])
    assert jobs.job_status(job['id'])['status'] == 'complete'
    assert len(calls) == 8 and calls[0]['session_id'] is None and calls[4]['session_id'] is None
    assert calls[1]['session_id'] and calls[2]['session_id'] is None
    assert calls[3]['session_id'] == calls[1]['session_id']
    assert all(c['prompt_version_id'] == pinned['id'] for c in calls)
    assert prompt_versions.get(source)['id'] != pinned['id']
    from app.observability.evaluation import evaluation_run

    for ident in job['run_ids']:
        run = evaluation_run(ident)
        assert run['golden_version_id'] == v['id'] and run['completed'] == 4
        assert run['results'][0]['model_calls'] == 3 and run['results'][0]['tool_calls'] == 2
        assert run['results'][0]['generation_latency_ms'] == 123
        assert run['summary']['bleu']['4'] == 1
        assert run['prompt_snapshot']['briefs'][0]['content'] == 'Shared guidance before evaluation'
        assert 'reference' not in calls[0]


def test_uploaded_output_scoring_needs_no_agent_index_and_never_self_scores(client, monkeypatch):
    monkeypatch.setattr(
        jobs.connections,
        'resolve',
        lambda ident: {'provider': 'openai', 'model': ident, 'base': 'https://example.invalid'},
    )
    v = golden.create(
        golden.DatasetWrite(
            name='Uploaded output',
            cases=[
                golden.GoldenCase(
                    question='What?',
                    reference='Cache repair is safe.',
                    provided_answer='Cache repair is safe.',
                    provided_contexts=['Cache repair requirements.'],
                )
            ],
        )
    )
    job = jobs.launch(
        jobs.Launch(
            golden_dataset_id=v['dataset_id'],
            version_id=v['id'],
            run_mode='provided',
            connection_ids=['judge'],
            ragas=False,
        ),
        spawn=False,
    )
    jobs.execute(job['id'])
    assert jobs.job_status(job['id'])['status'] == 'complete'
    row = store.mongo().agent_eval_results.find_one({'evaluation_id': job['run_ids'][0]})
    assert row['metrics']['ngrams']['bleu']['4'] == 1 and row['retrieved_contexts'] == [
        'Cache repair requirements.'
    ]
    assert row['generation_instrumentation'] == 'not_provided'
