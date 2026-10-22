"""Model-led investigation, project briefs and explicit capacity assumptions."""

import csv
import io
import json

import pytest
from app import store
from app.agent import transport
from app.agent.tools import Context
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    with TestClient(app) as client:
        yield client


def upload(client):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            'Issue key',
            'Summary',
            'Issue Type',
            'Status',
            'Status Category',
            'Project key',
            'Assignee',
            'Sprint',
            'Story Points',
            'Parent',
            'Description',
        ]
    )
    writer.writerows(
        [
            [
                'APP-1',
                'Login reliability',
                'Story',
                'In Progress',
                'In Progress',
                'APP',
                'Alex',
                'Sprint 7',
                5,
                '',
                'Improve sign-in reliability',
            ],
            [
                'APP-2',
                'Login audit',
                'Story',
                'Done',
                'Done',
                'APP',
                'Alex',
                'Sprint 7',
                3,
                '',
                'Audit sign-in events',
            ],
            [
                'APP-3',
                'Session timeout',
                'Story',
                'To Do',
                'To Do',
                'APP',
                'Sam',
                'Sprint 7',
                13,
                '',
                'Session controls',
            ],
            [
                'APP-4',
                'Password reset',
                'Story',
                'To Do',
                'To Do',
                'APP',
                'Jordan',
                'Sprint 7',
                '',
                '',
                'Recovery experience',
            ],
            [
                'APP-5',
                'Account history',
                'Task',
                'Done',
                'Done',
                'APP',
                'Taylor',
                'Sprint 6',
                2,
                '',
                'Historical work',
            ],
            [
                'APP-6',
                'Legacy task',
                'Task',
                'To Do',
                'To Do',
                'APP',
                'Inactive',
                'Sprint 7',
                1,
                '',
                'Historical owner',
            ],
            [
                'APP-10',
                'Platform epic',
                'Epic',
                'To Do',
                'To Do',
                'APP',
                'Alex',
                'Sprint 8',
                2,
                '',
                'Account platform',
            ],
            [
                'APP-11',
                'Platform task',
                'Story',
                'To Do',
                'To Do',
                'APP',
                'Alex',
                'Sprint 8',
                3,
                '10',
                'Part of platform',
            ],
        ]
    )
    result = client.post(
        '/api/imports', files={'file': ('management.csv', out.getvalue().encode(), 'text/csv')}
    )
    dataset = result.json()['id']
    store.save_people(
        dataset,
        [
            {
                'project': 'APP',
                'assignee': name,
                'is_developer': True,
                'is_active': name != 'Inactive',
                'work_areas': ['Backend'],
            }
            for name in ['Alex', 'Sam', 'Jordan', 'Taylor', 'Inactive']
        ],
    )
    return dataset


def test_project_context_validation_persistence_and_import_isolation(client):
    first, second = upload(client), upload(client)
    base = f'/api/datasets/{first}/agent/project-context'
    assert client.get(base).json()['content'] == ''
    saved = client.put(
        base + '?project=APP', json={'content': 'Goal: reliable sign-in. We use a 10-point planning budget.'}
    )
    assert saved.status_code == 200
    store.initialize()
    assert 'reliable sign-in' in client.get(base + '?project=APP').json()['content']
    assert client.get(base).json()['content'] == ''
    assert client.get(f'/api/datasets/{second}/agent/project-context?project=APP').json()['content'] == ''
    assert client.put(base + '?project=MISSING', json={'content': 'wrong'}).status_code == 404
    assert client.put(base, json={'content': 'x' * 12001}).status_code == 422
    assert client.put(base + '?project=APP', json={'content': ''}).json()['content'] == ''


def test_sprint_remaining_work_counts_all_unfinished_stages_in_one_query(client):
    dataset = upload(client)
    context = Context(dataset, 'APP', 'Sprint 7')
    context.context_scope = {'project': 'APP', 'sprint': 'Sprint 7', 'collection': 'backlog'}
    result = context.call('sprint_remaining_work', {'project': 'APP'})
    assert result['total_sprints'] == 3
    assert result['sprints_with_remaining_work'] == 2
    assert result['sprints_all_done'] == 1
    assert result['sprints_unknown_only'] == 0
    sprint = next(item for item in result['sprints'] if item['sprint'] == 'Sprint 7')
    assert (sprint['total'], sprint['remaining'], sprint['done']) == (5, 4, 1)
    assert sprint['remaining_statuses'] == {'In Progress': 1, 'To Do': 3}
    assert 'not status at sprint closure' in result['limitations']


def test_sprint_remaining_work_handles_custom_statuses_unknowns_and_multiple_memberships(client):
    content = (
        'Issue key,Summary,Status,Status Category,Project key,Sprint,Sprint,Issue Type\n'
        'APP-1,Custom review,Awaiting approval,In Progress,APP,Iteration A,Iteration B,Task\n'
        'APP-2,Released,Production,Done,APP,Iteration C,,Task\n'
        'APP-3,Unknown,Custom stage,,APP,Iteration D,,Task\n'
        'APP-4,Unscheduled,To Do,To Do,APP,,,Task\n'
        'APP-5,Testing,Testing,In Progress,APP,Iteration B,Iteration B,Task\n'
        'OPS-1,Other project,Done,Done,OPS,Iteration A,,Task\n'
    )
    response = client.post('/api/imports', files={'file': ('stages.csv', content.encode(), 'text/csv')})
    assert response.status_code == 202
    result = Context(response.json()['id']).call('sprint_remaining_work', {'project': '__all__'})
    assert result['total_sprints'] == 5
    assert result['sprints_with_remaining_work'] == 2
    assert result['sprints_all_done'] == 2
    assert result['sprints_unknown_only'] == 1
    assert result['unscheduled_tickets'] == 1
    sprint = next(item for item in result['sprints'] if item['sprint'] == 'Iteration B')
    assert sprint['total'] == 2
    assert sprint['remaining_statuses'] == {'Awaiting approval': 1, 'Testing': 1}


def test_capacity_uses_explicit_budget_and_keeps_unknown_estimates_unknown(client):
    dataset = upload(client)
    context = Context(dataset, 'APP', 'Sprint 7')
    args = {
        'project': 'APP',
        'sprint': 'Sprint 7',
        'points_per_developer': None,
        'basis': 'committed',
        'parent_policy': None,
    }
    assert 'define available capacity' in context.call('capacity_analysis', args)['clarification']
    result = context.call('capacity_analysis', {**args, 'points_per_developer': 10})
    people = {p['name']: p for p in result['people']}
    assert people['Alex']['committed_points'] == 8 and people['Alex']['headroom_points'] == 2
    assert people['Sam']['headroom_points'] == -3
    assert people['Jordan']['committed_points'] is None
    assert people['Jordan']['headroom_points'] is None and people['Jordan']['unestimated_tickets'] == 1
    assert people['Taylor']['headroom_points'] == 10 and people['Taylor']['assigned_tickets'] == 0
    assert 'Inactive' not in people
    open_load = context.call('capacity_analysis', {**args, 'points_per_developer': 10, 'basis': 'open'})
    assert next(p for p in open_load['people'] if p['name'] == 'Alex')['headroom_points'] == 5
    assert 'not prove calendar availability' in result['notes']


def test_capacity_parent_child_overlap_requires_an_estimate_convention(client):
    dataset = upload(client)
    context = Context(dataset, 'APP', 'Sprint 8')
    args = {
        'project': 'APP',
        'sprint': 'Sprint 8',
        'points_per_developer': 10,
        'basis': 'committed',
        'parent_policy': None,
    }
    result = context.call('capacity_analysis', args)
    assert result['estimated_parent_child_overlap'] == ['APP-10']
    assert next(p for p in result['people'] if p['name'] == 'Alex')['headroom_points'] is None
    assert next(p for p in result['people'] if p['name'] == 'Taylor')['headroom_points'] == 10
    leaf = context.call('capacity_analysis', {**args, 'parent_policy': 'leaf_only'})
    assert next(p for p in leaf['people'] if p['name'] == 'Alex')['headroom_points'] == 7


def test_default_chat_requires_ai_instead_of_automatic_snapshot_reports(client):
    dataset = upload(client)
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat', json={'message': 'Give me a project overview'}
    )
    assert result.status_code == 503 and 'Automatic report responses are disabled' in result.json()['detail']


def test_model_intent_then_evidence_then_streamed_synthesis_with_project_brief(client, monkeypatch):
    dataset = upload(client)
    client.put(
        f'/api/datasets/{dataset}/agent/project-context?project=APP',
        json={
            'content': 'Goal: reliable sign-in. Our planning budget is 10 points per developer per sprint.'
        },
    )
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://model/v1')
    requests = []
    responses = [
        {
            'tool_calls': [
                {
                    'id': 'p',
                    'function': {
                        'name': 'plan_investigation',
                        'arguments': json.dumps(
                            {
                                'intent': 'project delivery focus',
                                'retrieval': 'hybrid',
                                'steps': ['Inspect current work', 'Find goal-related work'],
                            }
                        ),
                    },
                }
            ]
        },
        {
            'tool_calls': [
                {'id': 'm', 'function': {'name': 'project_summary', 'arguments': '{"project":"APP"}'}}
            ]
        },
        {
            'tool_calls': [
                {
                    'id': 's',
                    'function': {
                        'name': 'search_tickets',
                        'arguments': '{"query":"sign-in reliability","project":"APP","sprint":null,"limit":3}',
                    },
                }
            ]
        },
        {
            'content': 'The current focus is reliable sign-in. Review the session controls and missing password-reset estimate before pulling more work.'
        },
    ]

    def request(client, url, headers, body, timeout, kind, emit=None):
        requests.append(body)
        item = responses.pop(0)
        if 'content' in item and emit:
            emit('text_delta', {'text': item['content'][:42]})
            emit('text_delta', {'text': item['content'][42:]})
        return {'choices': [{'message': item}]}

    monkeypatch.setattr(transport, 'request', request)
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'Give me a project overview', 'project': 'APP', 'stream': True},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    final = next(e for e in events if e['event'] == 'done')
    deltas = [e['text'] for e in events if e['event'] == 'text_delta']
    assert len(requests) == 4 and ''.join(deltas) == final['content']
    assert final['content'].startswith('The current focus') and final['mode'] == 'ai'
    assert final['charts'] == [] and final['details_markdown'] == ''
    assert any(t['tool'] == 'plan_investigation' for t in final['tools'])
    assert any(t['tool'] == 'search_tickets' for t in final['tools'])
    assert 'Our planning budget is 10 points' in str(requests[0]['messages'])
    assert 'Scrum Master' in requests[0]['messages'][0]['content']
    assert all('Application-prepared evidence' not in str(r) for r in requests)
    trace = store.mongo().agent_runs.find_one({'id': final['run_id']})
    assert trace['prompt_version']['number'] == 2
    assert 'Our planning budget is 10 points' in trace['prompt_version']['briefs'][0]['content']


def test_capacity_intent_requires_capacity_evidence_before_model_answer(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://model/v1')
    requests = []
    replies = [
        {
            'tool_calls': [
                {
                    'id': 'p',
                    'function': {
                        'name': 'plan_investigation',
                        'arguments': json.dumps(
                            {
                                'intent': 'capacity planning',
                                'retrieval': 'metadata',
                                'steps': ['Check explicit budget and assigned load'],
                            }
                        ),
                    },
                }
            ]
        },
        {
            'tool_calls': [
                {
                    'id': 'c',
                    'function': {
                        'name': 'capacity_analysis',
                        'arguments': json.dumps(
                            {
                                'project': 'APP',
                                'sprint': 'Sprint 7',
                                'points_per_developer': 10,
                                'basis': 'committed',
                                'parent_policy': None,
                            }
                        ),
                    },
                }
            ]
        },
        {
            'content': 'Alex has 2 points of planning headroom. Sam is 3 points over this assumption. Jordan is unknown because an estimate is missing.'
        },
    ]

    def request(client, url, headers, body, timeout, kind, emit=None):
        requests.append(body)
        return {'choices': [{'message': replies.pop(0)}]}

    monkeypatch.setattr(transport, 'request', request)
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'Who has headroom under our 10-point per developer budget?',
            'project': 'APP',
            'sprint': 'Sprint 7',
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()['skill'] == 'capacity'
    assert requests[0]['tool_choice'] == 'required' and len(requests[0]['tools']) == 1
    assert requests[1]['tool_choice'] == 'required'
    assert requests[2]['tool_choice'] == 'auto'
    assert 'project_summary' not in {t['function']['name'] for t in requests[1]['tools']}
    evidence = json.loads(requests[2]['messages'][-1]['content'])
    alex = next(p for p in evidence['people'] if p['name'] == 'Alex')
    assert alex['headroom_points'] == 2
    assert 'Jordan is unknown' in response.json()['content']
    assert response.json()['conversation_context']['capacity_rule']['points_per_developer'] == 10
    assert 'Planning assumption for APP: 10 points/developer' in response.json()['context_description']
