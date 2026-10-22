"""Adaptive evidence budgets preserve exact aggregates, recency and conversation scope."""

import csv
import io
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from app import store
from app.agent import context_budget, conversation, provider, transport
from app.agent.tools import Context
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    with TestClient(app) as client:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(
            [
                'Issue key',
                'Summary',
                'Issue Type',
                'Status',
                'Status Category',
                'Assignee',
                'Reporter',
                'Created',
                'Updated',
                'Description',
            ]
        )
        for number in range(1, 121):
            date = datetime(2026, 1, 1) + timedelta(days=number)
            updated = '2026-10-01T12:00:00' if number == 1 else date.isoformat()
            writer.writerow(
                [
                    f'APP-{number}',
                    f'Data platform work {number}',
                    'Story',
                    'In Progress',
                    'In Progress',
                    'Alex Example',
                    'Dana Reporter',
                    date.isoformat(),
                    updated,
                    'A detailed exported requirement. ' * 250,
                ]
            )
        response = client.post(
            '/api/imports',
            data={'prepare_agent': 'false'},
            files={'file': ('recent.csv', out.getvalue().encode(), 'text/csv')},
        )
        yield response.json()['id']


def test_aggregate_people_does_not_fetch_ticket_narratives(dataset):
    context = Context(dataset, 'APP')
    result = context.call('query_metadata', {'group_by': 'assignee'})
    assert result['total'] == 120
    assert result['groups'] == [{'name': 'Alex Example', 'count': 120}]
    assert result['distinct_groups'] == 1
    assert result['tickets'] == []
    assert 'Dana Reporter' not in json.dumps(result)


@pytest.mark.parametrize(
    'window,initial,maximum', [(4096, 10, 10), (8192, 30, 30), (32768, 30, 100), (65536, 30, 100)]
)
def test_recent_employee_samples_and_database_paging_follow_configured_budget(
    dataset, window, initial, maximum
):
    context = Context(dataset, 'APP')
    context.retrieval_limits = context_budget.settings({'context_window': window})
    result = context.call('employee_analysis', {'person': 'Alex Example'})
    assert result['assigned_tickets'] == 120
    assert len(result['example_tickets']) == initial
    assert result['example_tickets'][0]['key'] == 'APP-1'
    assert result['example_tickets'][1]['key'] == 'APP-120'
    assert result['example_coverage']['total'] == 120
    data = context.call(
        'query_metadata',
        {'filters': [{'field': 'assignee', 'operator': 'eq', 'value': 'Alex Example'}], 'limit': 100},
    )
    assert len(data['tickets']) == maximum
    assert data['tickets'][0]['key'] == 'APP-1'
    assert data['total'] == 120 and data['has_more']


def test_existing_mongodb_imports_get_date_sort_without_reopening_csv(dataset):
    store.mongo().issues.update_many(
        {'dataset_id': dataset}, {'$unset': {'sort_recent': '', 'sort_created': ''}}
    )
    result = Context(dataset, 'APP').call('query_metadata', {'limit': 5})
    assert result['tickets'][0]['key'] == 'APP-1'
    assert (
        store.mongo().issues.count_documents({'dataset_id': dataset, 'sort_recent': {'$exists': True}}) == 120
    )


def test_oversized_result_has_a_hard_budget_and_keeps_counts_and_latest_keys():
    source = {
        'total': 100,
        'metrics': {'total': 100},
        'tickets': [
            {
                'key': f'APP-{number}',
                'summary': 'A meaningful title',
                'description': 'requirement ' * 5000,
                'status': 'To Do',
                'irrelevant_custom_fields': ['noise' * 100] * 100,
            }
            for number in range(100, 0, -1)
        ],
    }
    packed = context_budget.bound_result(source, {'context_window': 4096})
    result = json.loads(packed)
    assert len(packed.encode()) <= context_budget.settings({'context_window': 4096})['tool_chars']
    assert result['total'] == 100
    assert 1 <= len(result['tickets']) <= 10
    assert result['tickets'][0]['key'] == 'APP-100'
    assert 'context_excerpt_note' in result
    assert source['tickets'][0]['description'].endswith('requirement ')


@pytest.mark.parametrize('protocol', ['chat', 'responses'])
def test_request_wide_sample_cap_preserves_tool_pairs_and_actual_coverage(protocol):
    cfg = {'context_window': 4096}
    ctx = SimpleNamespace(current_question='Review recent work', conversation_memory={})
    items = [{'role': 'user', 'content': 'Review recent work'}]
    for start in (1, 11):
        rows = [
            {'key': f'APP-{number}', 'summary': 'Platform work', 'status': 'To Do'}
            for number in range(start, start + 10)
        ]
        payload = json.dumps(
            {'total': 120, 'tickets': rows, 'ticket_sampling': {'shown': 10, 'matched': 120}}
        )
        call_id = f'call-{start}'
        if protocol == 'responses':
            items.extend(
                [
                    {
                        'type': 'function_call',
                        'call_id': call_id,
                        'name': 'query_metadata',
                        'arguments': '{}',
                    },
                    {'type': 'function_call_output', 'call_id': call_id, 'output': payload},
                ]
            )
        else:
            items.extend(
                [
                    {
                        'role': 'assistant',
                        'tool_calls': [
                            {
                                'id': call_id,
                                'type': 'function',
                                'function': {'name': 'query_metadata', 'arguments': '{}'},
                            }
                        ],
                    },
                    {'role': 'tool', 'tool_call_id': call_id, 'content': payload},
                ]
            )
    key = 'input' if protocol == 'responses' else 'messages'
    packed = context_budget.fit({key: items}, cfg, ctx)[key]
    results = [
        item for item in packed if item.get('role') == 'tool' or item.get('type') == 'function_call_output'
    ]
    keys = set()
    for result in results:
        data = json.loads(result.get('output', result.get('content')))
        assert data['total'] == 120
        assert data['ticket_sampling']['shown'] == len(data['tickets'])
        keys.update(row['key'] for row in data['tickets'])
        call_id = result.get('call_id', result.get('tool_call_id'))
        assert any(
            item.get('call_id') == call_id
            and item.get('type') == 'function_call'
            or any(call['id'] == call_id for call in item.get('tool_calls', []))
            for item in packed
        )
    assert keys == {f'APP-{number}' for number in range(11, 21)}


def test_large_window_preserves_twenty_recent_tickets_when_excerpts_are_long():
    source = {
        'assigned_tickets': 120,
        'example_coverage': {'shown': 30, 'total': 120},
        'example_tickets': [
            {
                'key': f'APP-{number}',
                'summary': 'Data work',
                'description': 'Details ' * 20000,
                'status': 'Done',
            }
            for number in range(120, 90, -1)
        ],
    }
    result = json.loads(context_budget.bound_result(source, {'context_window': 32768}))
    assert len(result['example_tickets']) >= 20
    assert result['example_coverage']['shown'] == len(result['example_tickets'])
    assert result['assigned_tickets'] == 120


@pytest.mark.parametrize('window', [2048, 4096, 8192, 32768])
@pytest.mark.parametrize('adapter', ['compatible', 'openai'])
def test_native_model_loop_answers_large_person_collection_with_fitting_requests(
    dataset, monkeypatch, window, adapter
):
    monkeypatch.setenv('JIRA_AI_PROVIDER', adapter)
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://model/v1')
    monkeypatch.setenv('JIRA_AI_MODELS', '')
    calls, events = [], []
    context = Context(dataset, 'APP', on_event=lambda event, data: events.append((event, data)))
    conversation.resolve(context, 'What does Alex Example work on?')
    cfg = provider.resolve()
    cfg['context_window'] = window
    monkeypatch.setattr(provider, 'resolve', lambda connection_id=None: cfg)

    def request(client, url, headers, body, timeout, protocol, emit):
        calls.append(body)
        limit = int(window * 0.9) - context_budget.settings(cfg)['output_reserve']
        assert context_budget.estimate(body) <= limit
        name = 'employee_analysis'
        if len(calls) == 1:
            assert name in {
                tool.get('name') or tool.get('function', {}).get('name') for tool in body.get('tools', [])
            }
        args = {'person': 'Alex Example'}
        call = {'name': name, 'arguments': json.dumps(args)}
        if len(calls) == 1:
            if protocol == 'responses':
                return {'output': [{'type': 'function_call', 'call_id': f'call-{len(calls)}', **call}]}
            return {
                'choices': [
                    {
                        'message': {
                            'role': 'assistant',
                            'content': '',
                            'tool_calls': [
                                {'id': f'call-{len(calls)}', 'type': 'function', 'function': call}
                            ],
                        }
                    }
                ]
            }
        answer = 'Recent examples show data platform work. This is a recent sample of 120 matching tickets.'
        return (
            {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': answer}]}]}
            if protocol == 'responses'
            else {'choices': [{'message': {'role': 'assistant', 'content': answer}}]}
        )

    monkeypatch.setattr(transport, 'request', request)
    answer, _ = provider.run(context, 'What does Alex Example work on?', [], [], False)
    assert '120 matching tickets' in answer
    assert len(calls) == 2
    assert all('Alex Example' in json.dumps(body) for body in calls)
    if window < 8192:
        assert any('optimis' in data.get('message', '') for event, data in events)
    assert cfg['context_window'] == window
    if window >= 32768:
        packets = [
            json.loads(item.get('output', item.get('content')))
            for item in calls[-1].get('input', calls[-1].get('messages', []))
            if item.get('type') == 'function_call_output' or item.get('role') == 'tool'
        ]
        examples = next(packet['example_tickets'] for packet in packets if 'example_tickets' in packet)
        assert 20 <= len(examples) <= 30
