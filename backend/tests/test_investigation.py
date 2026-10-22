"""Exact person/sprint filters and bounded selected-model evidence workers."""

import csv
import io
import json
import time
from datetime import datetime, timedelta

import pytest
from app import store
from app.agent import context_budget, conversation, grounding, index, investigation, provider, transport
from app.agent.retrieval_cache import MemoryRetrievalCache
from app.agent.tools import Context
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    with TestClient(app) as client:
        text = io.StringIO()
        writer = csv.writer(text)
        writer.writerow(
            [
                'Issue key',
                'Summary',
                'Issue Type',
                'Status',
                'Status Category',
                'Assignee',
                'Reporter',
                'Sprint',
                'Updated',
                'Description',
            ]
        )
        for number in range(1, 131):
            description = (
                'Ordinary delivery record.'
                if number != 130
                else 'The permit_sync_gate prevents publishing without approval.'
            )
            writer.writerow(
                [
                    f'APP-{number}',
                    'Routine delivery work',
                    'Story',
                    'In Progress',
                    'In Progress',
                    'ALEX EXAMPLE' if number % 2 else 'Alex Example',
                    'Dana Reporter',
                    'Delivery Sprint 43',
                    (datetime(2026, 1, 1) + timedelta(days=131 - number)).isoformat(),
                    description,
                ]
            )
        result = client.post(
            '/api/imports',
            data={'prepare_agent': 'false'},
            files={'file': ('investigation.csv', text.getvalue().encode(), 'text/csv')},
        )
        dataset = result.json()['id']
        index.reserve(dataset)
        index.build(dataset)
        yield dataset


def configured_context(dataset, effort='high', adapter='openai', window=32768):
    context = Context(dataset, 'APP', 'Delivery Sprint 43', retrieval_cache=MemoryRetrievalCache())
    context.investigation_effort = effort
    context.investigation_model_config = {
        'configured': True,
        'provider': adapter,
        'model': 'selected-model',
        'base': 'http://selected/v1',
        'key': 'synthetic-secret',
        'context_window': window,
    }
    context.retrieval_limits = context_budget.settings(context.investigation_model_config)
    context.model_requests = 0
    context.agent_deadline = time.monotonic() + 120
    conversation.resolve(context, 'In APP sprint 43, locate the specific approval requirement')
    return context


def reply(protocol, text):
    return (
        {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
        if protocol == 'responses'
        else {'choices': [{'message': {'content': text}}]}
    )


@pytest.mark.parametrize('name', ['alex', 'ALEX', 'aLeX eXaMpLe'])
def test_short_subject_name_and_sprint_filter_match_case_variants(dataset, name):
    context = Context(dataset, 'APP')
    conversation.resolve(context, f'what did {name} work on in sprint 43')
    result = context.call(
        'query_metadata', {'filters': [{'field': 'Assignee', 'operator': 'eq', 'value': name}]}
    )
    assert not context.memory_clarification
    assert result['total'] == 130
    assert result['scope'] == {'project': 'APP', 'sprint': 'Delivery Sprint 43'}
    assert context.call('find_people', {'query': name})['total_matches'] == 1
    evidence = grounding.prefetch(context, context.question, [])
    assert evidence[0]['verified_assignment_query']['total'] == 130
    assert context.call('employee_analysis', {'person': name})['assigned_tickets'] == 130


def test_ambiguous_people_and_duplicate_sprint_projects_require_clarification(dataset):
    store.mongo().issues.update_one(
        {'dataset_id': dataset, 'key': 'APP-3'}, {'$set': {'summary.assignee': 'Alex Other'}}
    )
    context = Context(dataset)
    conversation.resolve(context, 'what did alex work on in sprint 43')
    assert context.clarification_needed and 'Which person' in context.memory_clarification
    result = context.call(
        'query_metadata', {'filters': [{'field': 'assignee', 'operator': 'eq', 'value': 'Alex'}]}
    )
    assert result['ambiguous']
    store.mongo().issues.update_one(
        {'dataset_id': dataset, 'key': 'APP-3'},
        {'$set': {'summary.project_key': 'OPS', 'summary.project_name': 'Operations', 'project': 'OPS'}},
    )
    context = Context(dataset)
    conversation.resolve(context, 'Summarize sprint 43')
    assert context.clarification_needed and 'Which project' in context.memory_clarification


@pytest.mark.parametrize('adapter', ['compatible', 'openai', 'gemini'])
def test_high_effort_continues_to_older_evidence_with_same_selected_model(dataset, monkeypatch, adapter):
    context = configured_context(dataset, adapter=adapter)
    original = investigation.candidates

    def ordered(*args):
        pool, total = original(*args)
        return sorted(pool, key=lambda row: int(row['issue_key'].split('-')[1])), total

    monkeypatch.setattr(investigation, 'candidates', ordered)
    calls = []

    def request(client, url, headers, body, timeout, protocol, emit=None):
        calls.append(body)
        assert body['model'] == 'selected-model'
        assert headers['Authorization'] == 'Bearer synthetic-secret'
        assert context_budget.estimate(body) < 32768 - body.get('max_output_tokens', body.get('max_tokens'))
        messages = body.get('input', body.get('messages'))
        source = json.loads(messages[-1]['content'])['sources']
        findings = [
            {
                'id': row['id'],
                'score': 4,
                'quote': 'The permit_sync_gate prevents publishing without approval.',
            }
            for row in source
            if 'permit_sync_gate' in row['text']
        ]
        return reply(protocol, json.dumps({'findings': findings}))

    monkeypatch.setattr(transport, 'request', request)
    first = context.call('investigate_tickets', {'query': 'Locate the specific approval requirement'})
    assert 'evidence' in first, first
    assert not first['evidence'] and first['coverage']['has_more']
    second = context.call('investigate_tickets', {'query': 'Locate the specific approval requirement'})
    assert second['evidence'][0]['key'] == 'APP-130'
    assert second['coverage']['chunks_checked_by_model'] == 130
    assert not second['coverage']['has_more']
    assert len(calls) == 7 < investigation.policy(context)['requests']
    assert 'permit_sync_gate' in context_budget.bound_result(second, context.investigation_model_config)


def test_low_effort_is_bounded_and_does_not_claim_absence(dataset, monkeypatch):
    context = configured_context(dataset, 'low')
    monkeypatch.setattr(transport, 'request', lambda *args: reply('responses', '{"findings":[]}'))
    result = context.call('investigate_tickets', {'query': 'Look for a specific decision'})
    assert context.model_requests == 1
    assert result['coverage']['effort_exhausted']
    assert result['coverage']['remaining_chunks'] > 0
    assert not result['coverage']['has_more']
    assert 'Never treat unreviewed' in result['instruction']


def test_worker_rejects_fabricated_quotes_and_reuses_only_exact_scoped_evidence(dataset, monkeypatch):
    context = configured_context(dataset)
    source = [{'id': 'chunk-a', 'issue_key': 'APP-1', 'content': 'Only this exact source text is evidence.'}]
    calls = []

    def request(*args):
        calls.append(True)
        return reply(
            'responses',
            json.dumps(
                {
                    'findings': [
                        {
                            'id': 'chunk-a',
                            'score': 4,
                            'quote': 'A fabricated claim that is not in the ticket.',
                        }
                    ]
                }
            ),
        )

    monkeypatch.setattr(transport, 'request', request)
    assert investigation.worker(context, 'Question', source) == ([], False)
    assert investigation.worker(context, 'Question', source) == ([], True)
    assert len(calls) == 1
    investigation.worker(context, 'Different question', source)
    assert len(calls) == 2


def test_workers_fit_small_configured_windows_and_do_not_drop_source_tail(dataset, monkeypatch):
    context = configured_context(dataset, window=4096)
    sizes = []

    def request(client, url, headers, body, timeout, protocol, emit=None):
        sizes.append(context_budget.estimate(body))
        assert (
            sizes[-1]
            <= int(4096 * 0.9) - context_budget.settings(context.investigation_model_config)['output_reserve']
        )
        return reply(protocol, '{"findings":[]}')

    monkeypatch.setattr(transport, 'request', request)
    context.call('investigate_tickets', {'query': 'Locate the specific approval requirement'})
    assert sizes


def test_assignment_absence_draft_is_corrected_without_streaming_false_claim(dataset, monkeypatch):
    context = configured_context(dataset, adapter='compatible')
    conversation.resolve(context, 'what did alex work on in sprint 43')
    monkeypatch.setattr(provider, 'resolve', lambda *args: context.investigation_model_config)
    emitted, calls = [], []
    context.on_event = lambda event, data: emitted.append((event, data))

    def request(client, url, headers, body, timeout, protocol, emit=None):
        calls.append(body)
        text = (
            'Alex had no assigned tickets.'
            if len(calls) == 1
            else 'The export has 130 assigned tickets for Alex in Sprint 43.'
        )
        if emit:
            emit('text_delta', {'text': text})
        return reply(protocol, text)

    monkeypatch.setattr(transport, 'request', request)
    answer, _ = provider.run(context, context.question, [], [])
    assert '130 assigned' in answer and len(calls) == 2
    assert all('no assigned tickets' not in data.get('text', '') for event, data in emitted)


def test_nemotron_local_preset_needs_no_key_and_declares_native_window():
    with TestClient(app) as client:
        preset = next(
            p
            for p in client.get('/api/agent/connections').json()['presets']
            if p['id'] == 'nemotron-cascade-8b'
        )
        assert preset['provider'] == 'compatible'
        assert not preset['requires_key']
        assert preset['model'] == 'agileplanner-nemotron-cascade:8b'
        assert preset['context_window'] == 32768
        assert preset['base'].endswith(':11434/v1')
