"""Ticket evidence survives raw-field budgets without opening attachment contents."""

import csv
import io
import json

import pytest
from app import store
from app.agent import conversation, grounding, index
from app.agent.tools import Context
from app.main import app
from fastapi.testclient import TestClient
from test_reference_context import configure, model


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    headers = [
        'Issue key',
        'Summary',
        'Issue Type',
        'Status',
        'Status Category',
        'Project key',
        'Description',
        'Parent',
        'Outward issue link (Blocks)',
        'Custom field (Acceptance Criteria)',
        'Attachment',
        'Attachment',
        'Comment',
        'Comment',
        'Labels',
    ]
    rows = [
        [
            'APP-1',
            'Parent project',
            'Epic',
            'In Progress',
            'In Progress',
            'APP',
            'Project scope',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            'shared',
        ],
        [
            'APP-2',
            'Load partner records',
            'Story',
            'Done',
            'Done',
            'APP',
            '[^plan.xlsx]\n!screen.png|width=50!\n\nh3. Acceptance Criteria\nReject invalid rows\nh3. Notes\nMore context',
            '1',
            'APP-3',
            'Log validation failures',
            'today;author;plan.xlsx;https://files.invalid/plan.xlsx?secret=hidden',
            'today;author;screen.png;https://files.invalid/screen.png',
            'Added data in DEV and QA',
            'Verified QA tables',
            'shared',
        ],
        [
            'APP-3',
            'Release validation',
            'Task',
            'To Do',
            'To Do',
            'APP',
            'Check counts',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            'shared',
        ],
        [
            'APP-4',
            'Upstream source',
            'Task',
            'Done',
            'Done',
            'APP',
            'Prepare source',
            '',
            'APP-2',
            '',
            '',
            '',
            '',
            '',
            '',
        ],
        [
            'APP-5',
            'Unrelated shared label',
            'Task',
            'Done',
            'Done',
            'APP',
            'Unrelated work',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            'shared',
        ],
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    with TestClient(app) as client:
        imported = client.post('/api/imports', files={'file': ('evidence.csv', output.getvalue().encode())})
        assert imported.status_code == 202
        yield client, imported.json()['id']


def test_ticket_packet_includes_explicit_relationships_criteria_comments_and_files(dataset):
    _, ident = dataset
    context = Context(ident)
    packet = context.get_ticket('APP-2')['ticket_context']
    assert packet['related_work']['parent']['summary'] == 'Parent project'
    assert {link['key']: link['direction'] for link in packet['related_work']['links']} == {
        'APP-3': 'outgoing',
        'APP-4': 'incoming',
    }
    assert 'APP-5' not in json.dumps(packet['related_work'])
    assert packet['acceptance_criteria']['count'] == 2
    assert 'Reject invalid rows' in json.dumps(packet['acceptance_criteria'])
    assert 'More context' not in json.dumps(packet['acceptance_criteria'])
    assert packet['attachments']['count'] == 2
    assert {item['name'] for item in packet['attachments']['items']} == {'plan.xlsx', 'screen.png'}
    assert packet['attachments']['contents_available'] is False
    assert 'secret=hidden' not in json.dumps(packet)
    assert packet['comments']['count'] == 2
    assert packet['related_work']['links_count'] == 2
    assert {'APP-1', 'APP-2', 'APP-3', 'APP-4'} <= set(context.citations)
    assert context.get_ticket('APP-1')['ticket_context']['related_work']['children'][0]['key'] == 'APP-2'
    assert context.get_ticket('APP-3')['ticket_context']['related_work']['links'][0]['key'] == 'APP-2'


def test_attachment_versions_inline_references_and_absence_are_distinct(dataset):
    _, ident = dataset
    record = store.issue(ident, 'APP-3')
    record['details']['fields'].update(
        {
            'Attachment': [
                'date;author;plan.xlsx;https://files.invalid/one',
                'date;author;plan.xlsx;https://files.invalid/two',
            ],
            'Description': ['[^plan.xlsx] and [^missing.pdf]'],
        }
    )
    store.save_issues(ident, [(record['summary'], record['details'])])
    packet = Context(ident).get_ticket('APP-3')['ticket_context']
    assert packet['attachments']['count'] == 3
    assert len([item for item in packet['attachments']['items'] if item['name'] == 'plan.xlsx']) == 2
    assert (
        next(item for item in packet['attachments']['items'] if item['name'] == 'missing.pdf')[
            'listed_in_export'
        ]
        is False
    )
    empty = Context(ident).get_ticket('APP-5')['ticket_context']
    assert empty['attachments']['count'] == empty['acceptance_criteria']['count'] == 0
    assert empty['related_work']['parent'] is None
    assert empty['related_work']['links'] == []


def test_missing_link_is_preserved_as_unresolved(dataset):
    _, ident = dataset
    record = store.issue(ident, 'APP-3')
    record['details']['fields']['Outward issue link (Blocks)'] = ['MISSING-99']
    store.save_issues(ident, [(record['summary'], record['details'])])
    packet = Context(ident).get_ticket('APP-3')['ticket_context']
    missing = next(item for item in packet['related_work']['links'] if item.get('reference') == 'MISSING-99')
    assert missing['unresolved'] == 'not_in_export'
    assert 'key' not in missing


@pytest.mark.parametrize('provider', ['compatible', 'openai'])
def test_ticket_improvement_searches_requirements_and_reads_related_comments(dataset, monkeypatch, provider):
    client, ident = dataset
    record = store.issue(ident, 'APP-3')
    record['details']['fields'].update(
        {
            'Description': ['Load partner records and reject invalid rows; log validation failures.'],
            'Custom field (Comments)': [
                'Use a quarantine table for rejected records and replay after correction.'
            ],
        }
    )
    store.save_issues(ident, [(record['summary'], record['details'])])
    index.build(ident)
    connection = configure(client, monkeypatch, provider)
    requests = model(
        monkeypatch,
        [
            'Suggested approach: validate incoming rows and quarantine failures, following the related APP-3 discussion.'
        ],
    )
    response = client.post(
        f'/api/datasets/{ident}/agent/chat',
        json={
            'message': 'Improve APP-2 description and suggest a solution with code.',
            'connection_id': connection,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert any(item['tool'] == 'search_tickets' for item in result['tools'])
    prompt = json.dumps(requests[0])
    assert 'similar_tickets' in prompt and 'quarantine table' in prompt
    assert 'Custom field (Comments)' in prompt
    ctx = Context(ident)
    conversation.resolve(ctx, 'Improve APP-2 description')
    evidence = grounding.prefetch(ctx, 'Improve APP-2 description', [])
    related = evidence[-1]['similar_tickets']
    assert related and all(item['ticket']['key'] != 'APP-2' for item in related)
    queries = [key for key in ctx.tool_cache if json.loads(key)[0] == 'search_tickets']
    query = json.loads(queries[0])[1]['query']
    assert 'Load partner records' in query and 'Reject invalid rows' in query
    assert any(
        item['ticket']['key'] == 'APP-3' and item['ticket_context']['comments']['count'] for item in related
    )


@pytest.mark.parametrize('provider', ['compatible', 'openai'])
def test_automatic_evidence_preserves_ticket_packet_for_model_despite_large_fields(
    dataset, monkeypatch, provider
):
    client, ident = dataset
    record = store.issue(ident, 'APP-2')
    record['details']['fields'] = {'Large first field': ['x' * 14000] * 8, **record['details']['fields']}
    store.save_issues(ident, [(record['summary'], record['details'])])
    context = Context(ident)
    conversation.resolve(context, 'Explain APP-2')
    evidence = grounding.prefetch(context, 'Explain APP-2', [])
    assert evidence[0]['ticket_context']['attachments']['count'] == 2
    assert evidence[0]['ticket_context']['related_work']['links_count'] == 2
    assert context.get_ticket('APP-2')['fields_truncated']
    connection = configure(client, monkeypatch, provider)
    requests = model(
        monkeypatch,
        [
            'APP-2 loads partner records. Two attachments are listed; their contents have not been inspected. Check plan.xlsx and screen.png in Jira.'
        ],
    )
    result = client.post(
        f'/api/datasets/{ident}/agent/chat', json={'message': 'Explain APP-2', 'connection_id': connection}
    )
    assert result.status_code == 200, result.text
    body = json.dumps(requests[0])
    assert 'ticket_context' in body and 'contents_available' in body and 'plan.xlsx' in body
    assert 'acceptance_criteria' in body and 'Upstream source' in body
    assert [tool['tool'] for tool in result.json()['tools']] == ['get_ticket']
