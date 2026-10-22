"""Clarification before guessing, and complete ownership answers for referenced lists."""

import json

import pytest
from app import store
from app.agent import conversation, grounding, history_store, reference_context, transport
from app.agent.tools import Context
from app.main import app
from fastapi.testclient import TestClient

CSV = b"""Issue key,Summary,Issue Type,Status,Status Category,Assignee,Reporter,Description
APP-1,Validation baseline,Story,Done,Done,Ana,Lee,Validate input records
APP-2,Health checks,Story,Testing,In Progress,Ana,Lee,Check pipeline health
APP-3,Audit tables,Task,To Do,To Do,Bo,Lee,Record audit events
APP-4,Quality rules,Story,To Do,To Do,Bo,Lee,Validate data quality
APP-5,Search validation,Task,To Do,To Do,,Lee,Check search results
"""
RELATED = ['APP-2', 'APP-3', 'APP-4', 'APP-5']


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    with TestClient(app) as client:
        yield client


def upload(client):
    response = client.post('/api/imports', files={'file': ('references.csv', CSV)})
    assert response.status_code == 202
    return response.json()['id']


def configure(client, monkeypatch, provider):
    if provider == 'gemini':
        response = client.post(
            '/api/agent/connections',
            json={'name': 'Test Gemini', 'provider': 'gemini', 'model': 'test', 'api_key': 'test-only'},
        )
        return response.json()['id']
    monkeypatch.setenv('JIRA_AI_PROVIDER', provider)
    monkeypatch.setenv('JIRA_AI_MODEL', 'test')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://model/v1')
    monkeypatch.setenv('JIRA_AI_API_KEY', 'test-only')
    return None


def model(monkeypatch, replies):
    requests = []

    def request(client, url, headers, body, timeout, kind, emit=None):
        requests.append(body)
        reply = replies.pop(0)
        if isinstance(reply, str):
            if emit:
                emit('text_delta', {'text': reply})
            if kind == 'responses':
                return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': reply}]}]}
            return {'choices': [{'message': {'content': reply}}]}
        name, args = reply
        if kind == 'responses':
            return {
                'output': [
                    {
                        'type': 'function_call',
                        'name': name,
                        'arguments': json.dumps(args),
                        'call_id': str(len(requests)),
                    }
                ]
            }
        return {
            'choices': [
                {
                    'message': {
                        'tool_calls': [
                            {
                                'id': str(len(requests)),
                                'function': {'name': name, 'arguments': json.dumps(args)},
                            }
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr(transport, 'request', request)
    return requests


def seed(dataset, state, user, answer, sources=()):
    history_store.save_turn(
        dataset,
        'existing-chat',
        'APP',
        'today',
        state,
        {'content': user},
        {'content': answer, 'sources': list(sources), 'tools': []},
    )


def plan(intent='ownership', retrieval='metadata'):
    return (
        'plan_investigation',
        {'intent': intent, 'retrieval': retrieval, 'steps': ['Check the intended ticket set']},
    )


@pytest.mark.parametrize('provider', ['compatible', 'openai', 'gemini'])
@pytest.mark.parametrize('selection', ['Health checks', 'the second one'])
def test_ambiguous_singular_waits_for_selection_then_retrieves_selected_ticket(
    client, monkeypatch, provider, selection
):
    dataset = upload(client)
    state = conversation.empty()
    state.update(person={'name': 'Ana', 'field': 'assignee'}, focus='person', topic='more in depth')
    seed(
        dataset,
        state,
        'Analyze their points per sprint',
        'Examples include APP-1, APP-2 and APP-3.',
        [{'key': 'APP-3'}],
    )
    connection = configure(client, monkeypatch, provider)
    requests = model(
        monkeypatch,
        [('get_ticket', {'reference': 'APP-3'}), 'Which ticket do you mean—APP-1, APP-2, or APP-3?'],
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'explain this ticket',
            'session_id': 'existing-chat',
            'connection_id': connection,
            'stream': True,
        },
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    result = next(item for item in events if item['event'] == 'done')
    assert result['content'].startswith('Which ticket')
    assert result['tools'] == [] and result['sources'] == []
    assert requests[0]['tool_choice'] == 'none' and requests[0]['tools'] == []
    assert result['conversation_context']['pending_ticket_reference'] == ['APP-1', 'APP-2', 'APP-3']
    store.initialize()
    model(monkeypatch, ['APP-2 checks pipeline health. Ana is its current assignee.'])
    chosen = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': selection, 'session_id': 'existing-chat', 'connection_id': connection},
    ).json()
    assert chosen['mode'] == 'ai' and chosen['content'].startswith('APP-2')
    assert [item['tool'] for item in chosen['tools']] == ['get_ticket']
    assert chosen['conversation_context']['tickets'] == ['APP-2']
    assert chosen['conversation_context']['pending_ticket_reference'] == []


@pytest.mark.parametrize('provider', ['compatible', 'openai', 'gemini'])
def test_plural_followup_preserves_ownership_and_covers_all_four_tickets(client, monkeypatch, provider):
    dataset = upload(client)
    state = conversation.empty()
    state.update(focus='ticket', tickets=['APP-1'], ticket_set=RELATED)
    seed(
        dataset,
        state,
        'Find related work for APP-1',
        'Related work:\n' + '\n'.join('- ' + key for key in RELATED),
    )
    connection = configure(client, monkeypatch, provider)
    answer = 'Current assignees:\n- APP-2: Ana\n- APP-3: Bo\n- APP-4: Bo\n- APP-5: Unassigned\nThese are snapshot assignments.'
    requests = model(
        monkeypatch,
        [
            plan(),
            ('get_ticket', {'reference': 'APP-2'}),
            'Incomplete answer about one ticket.',
            ('ticket_ownership', {'references': RELATED, 'project': None}),
            'APP-2: Ana.',
            answer,
        ],
    )
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'who usually handles these tickets',
            'session_id': 'existing-chat',
            'connection_id': connection,
            'stream': True,
        },
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    result = next(item for item in events if item['event'] == 'done')
    assert ''.join(item['text'] for item in events if item['event'] == 'text_delta') == answer
    assert result['conversation_context']['ticket_set'] == RELATED
    assert result['conversation_context']['ticket_set_intent'] == 'ownership'
    assert {item['key'] for item in result['sources']} >= set(RELATED)
    assert requests[2]['tool_choice'] == 'required'
    requests = model(
        monkeypatch, [plan(), ('ticket_ownership', {'references': RELATED, 'project': None}), answer]
    )
    follow = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'okay, what about the other ticekts mentioned above response',
            'session_id': 'existing-chat',
            'connection_id': connection,
        },
    ).json()
    assert follow['content'] == answer
    assert [item['tool'] for item in follow['tools']] == ['plan_investigation', 'ticket_ownership']
    assert set(follow['conversation_context']['ticket_set']) == set(RELATED)
    assert 'identify current assignees for ALL' in str(requests[0])
    assert 'Lee' not in follow['content']


def test_model_can_choose_to_clarify_without_being_forced_to_retrieve(client, monkeypatch):
    dataset = upload(client)
    connection = configure(client, monkeypatch, 'compatible')
    requests = model(
        monkeypatch,
        [
            plan('define available capacity', 'clarify'),
            'What does available capacity mean for your team, and which sprint should I check?',
        ],
    )
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat', json={'message': 'Who is free?', 'connection_id': connection}
    ).json()
    assert result['content'].startswith('What does available')
    assert requests[1]['tool_choice'] == 'none' and requests[1]['tools'] == []
    assert [item['tool'] for item in result['tools']] == ['plan_investigation']


def test_unique_focus_and_single_attachment_do_not_require_redundant_clarification(client):
    dataset = upload(client)
    for attachments, history in [
        (['APP-2'], []),
        (
            [],
            [
                {'role': 'user', 'content': 'Explain APP-2'},
                {
                    'role': 'assistant',
                    'content': 'APP-2 is related to APP-3.',
                    'sources': [{'key': key} for key in RELATED],
                },
            ],
        ),
    ]:
        context = Context(dataset)
        conversation.resolve(context, 'explain this ticket')
        evidence = grounding.prefetch(context, 'explain this ticket', attachments, history)
        assert [item['ticket']['key'] for item in evidence] == ['APP-2']
        assert not getattr(context, 'reference_clarification', False)
    context = Context(dataset)
    conversation.resolve(context, 'explain this ticket')
    assert grounding.prefetch(context, 'explain this ticket', ['APP-2', 'APP-3']) == []
    assert context.reference_clarification


def test_discussed_list_comes_from_visible_verified_answer_not_extra_sources(client):
    dataset = upload(client)
    context = Context(dataset)
    conversation.resolve(context, 'Find related tickets')
    for key in ['APP-1', *RELATED]:
        context.call('get_ticket', {'reference': key})
    reference_context.remember(
        context,
        'Find related tickets',
        'Like APP-1:\n- APP-2: Health\n- APP-3: Audit\n- APP-4: Quality\n- APP-5: Search',
    )
    assert context.conversation_memory['ticket_set'] == RELATED
    assert context.conversation_memory['tickets'] == []


def test_reporter_followup_keeps_role_distinct_from_assignee(client):
    dataset = upload(client)
    state = conversation.empty()
    state['ticket_set'] = RELATED
    seed(dataset, state, 'Find related work', 'Related:\n' + '\n'.join('- ' + key for key in RELATED))
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'who reported these tickets', 'session_id': 'existing-chat', 'mode': 'retrieval'},
    ).json()
    assert result['conversation_context']['ticket_set_role'] == 'reporter'
    assert all(key in result['content'] for key in RELATED)
    assert result['content'].count('Lee') == 4 and ': Bo' not in result['content']


def test_numeric_ownership_target_resolves_to_canonical_key(client):
    dataset = upload(client)
    context = Context(dataset)
    conversation.resolve(context, 'who handles ticket 2')
    reference_context.prepare(context, 'who handles ticket 2')
    assert context.reference_targets == ['APP-2']
    result = context.call('ticket_ownership', {'references': context.reference_targets})
    assert result['tickets'][0]['assignee'] == 'Ana'
    assert context.ownership_verified == {'APP-2'}


def test_assistant_initiated_ticket_guess_does_not_become_user_selection(client):
    dataset = upload(client)
    context = Context(dataset)
    conversation.resolve(context, 'explain this ticket')
    history = [
        {'role': 'user', 'content': 'Who is working on validation?'},
        {
            'role': 'assistant',
            'content': 'APP-3: Audit tables',
            'sources': [{'key': 'APP-3'}],
            'tools': [{'tool': 'get_ticket', 'ok': True}],
        },
    ]
    assert grounding.prefetch(context, 'explain this ticket', [], history) == []
    assert context.reference_clarification


def test_old_conversation_recovers_full_related_list_and_ownership_intent(client):
    dataset = upload(client)
    state = conversation.empty()
    state.update(focus='ticket', tickets=['APP-1'])
    state.pop('ticket_set')
    state.pop('ticket_set_intent')
    seed(
        dataset,
        state,
        'are there other tickets similar to this one',
        'Like APP-1:\n' + '\n'.join('- ' + key for key in RELATED),
    )
    history_store.save_turn(
        dataset,
        'existing-chat',
        'APP',
        'today',
        state,
        {'content': 'who usually handles these tickets'},
        {
            'content': 'Ana handles this work.\n- Evidence: APP-1 and APP-2.',
            'sources': [{'key': 'APP-1'}, {'key': 'APP-2'}],
        },
    )
    history_store.save_turn(
        dataset,
        'existing-chat',
        'APP',
        'today',
        state,
        {'content': 'okay, what about the other tickets mentioned above response'},
        {'content': '- APP-2: Health checks description only.', 'sources': [{'key': 'APP-2'}]},
    )
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'what about the other tickets mentioned above',
            'session_id': 'existing-chat',
            'mode': 'retrieval',
        },
    ).json()
    assert result['conversation_context']['ticket_set'] == RELATED
    assert result['conversation_context']['ticket_set_intent'] == 'ownership'
    assert [tool['tool'] for tool in result['tools']] == ['ticket_ownership']
    assert all(key in result['content'] for key in RELATED)
    assert ': Bo' in result['content'] and ': Unassigned' in result['content']


def test_new_attribute_question_does_not_inherit_previous_ownership_task(client):
    dataset = upload(client)
    state = conversation.empty()
    state.update(ticket_set=RELATED, ticket_set_intent='ownership')
    context = Context(dataset)
    conversation.resolve(context, 'what about the severity of these tickets', state)
    reference_context.prepare(context, 'what about the severity of these tickets')
    assert context.reference_task != 'ownership'


@pytest.mark.parametrize('provider', ['compatible', 'openai'])
def test_open_ticket_is_grounded_page_context_and_survives_drawer_close(client, monkeypatch, provider):
    dataset = upload(client)
    state = conversation.empty()
    state.update(
        focus='ticket',
        tickets=['APP-1'],
        person={'name': 'Bo', 'field': 'assignee'},
        filters=[{'field': 'status', 'operator': 'eq', 'value': 'To Do'}],
    )
    seed(dataset, state, 'Explain APP-1', 'APP-1 validates records.')
    connection = configure(client, monkeypatch, provider)
    requests = model(monkeypatch, ['APP-2 checks pipeline health and is assigned to Ana.'])
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'explain this ticket',
            'page_ticket': 'app-2',
            'session_id': 'existing-chat',
            'connection_id': connection,
        },
    ).json()
    assert result['content'].startswith('APP-2')
    assert 'APP-2' in {item['key'] for item in result['sources']}
    assert result['conversation_context']['tickets'] == ['APP-2']
    assert result['conversation_context']['person'] is None
    assert result['conversation_context']['filters'] == []
    assert not result['conversation_context']['pending_ticket_reference']
    assert any('"open_ticket": "APP-2"' in json.dumps(body).replace('\\"', '"') for body in requests)
    model(monkeypatch, ['APP-2 is assigned to Ana.'])
    followup = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'explain this ticket', 'session_id': 'existing-chat', 'connection_id': connection},
    ).json()
    assert followup['conversation_context']['tickets'] == ['APP-2']


@pytest.mark.parametrize(
    'page_ticket,enabled,expected',
    [('APP-2', True, 'APP-2'), ('APP-3', True, 'APP-3'), ('APP-2', False, None), ('', True, None)],
)
def test_open_ticket_hint_is_current_optional_and_saved(client, page_ticket, enabled, expected):
    dataset = upload(client)
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'explain this ticket',
            'page_ticket': page_ticket,
            'use_page_context': enabled,
            'mode': 'retrieval',
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result['page_hint']['ticket'] == page_ticket
    assert result['page_hint']['enabled'] == enabled
    if expected:
        assert result['conversation_context']['tickets'] == [expected]
        assert expected in {item['key'] for item in result['sources']}
    else:
        assert result['tools'] == []
        assert 'Which ticket' in result['content']


@pytest.mark.parametrize(
    'message,attachments,expected',
    [
        ('Explain APP-1', [], 'APP-1'),
        ('explain this ticket', ['APP-3'], 'APP-3'),
        ('explain ticket 4', [], 'APP-4'),
    ],
)
def test_explicit_ticket_and_attachment_override_open_drawer(client, message, attachments, expected):
    dataset = upload(client)
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': message, 'page_ticket': 'APP-2', 'attachments': attachments, 'mode': 'retrieval'},
    ).json()
    assert expected in {item['key'] for item in result['sources']}
    assert result['conversation_context']['tickets'] == [expected]


def test_invalid_open_ticket_is_graceful_and_disabled_hints_are_ignored(client):
    dataset = upload(client)
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': 'explain this ticket', 'page_ticket': 'OTHER-9', 'mode': 'retrieval'},
    )
    assert response.status_code == 422
    assert 'open ticket is outside this import' in response.json()['detail']
    ignored = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'explain this ticket',
            'page_ticket': 'OTHER-9',
            'use_page_context': False,
            'mode': 'retrieval',
        },
    )
    assert ignored.status_code == 200
    assert ignored.json()['tools'] == []


@pytest.mark.parametrize(
    'message', ['Summarize this sprint', 'Give me a project overview', 'Show high priority tickets']
)
def test_open_drawer_does_not_turn_broader_questions_into_ticket_selection(client, message):
    dataset = upload(client)
    context = Context(dataset, page_ticket='APP-2')
    conversation.resolve(context, message)
    reference_context.prepare(context, message)
    assert context.reference_targets == []
    assert not getattr(context, 'reference_clarification', False)
