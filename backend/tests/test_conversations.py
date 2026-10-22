import csv
import io
import json

import httpx
import pytest
from app import store
from app.agent import context_budget, conversation, provider
from app.agent.tools import Context
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    with TestClient(app) as c:
        yield c


def upload(client):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            'Issue key',
            'Summary',
            'Issue Type',
            'Status',
            'Status Category',
            'Project key',
            'Assignee',
            'Reporter',
            'Priority',
            'Sprint',
            'Description',
        ]
    )
    for row in [
        [
            'APP-1',
            'API migration',
            'Story',
            'Testing',
            'In Progress',
            'APP',
            'Ana',
            'Lee',
            'High',
            'Delivery Cycle 7',
            'Authentication migration ' + ('detail ' * 1600),
        ],
        [
            'APP-2',
            'Health checks',
            'Task',
            'In Progress',
            'In Progress',
            'APP',
            'Ana',
            'Lee',
            'Medium',
            'Delivery Cycle 7',
            'Health checks',
        ],
        [
            'APP-3',
            'Cache fix',
            'Bug',
            'To Do',
            'To Do',
            'APP',
            'Bo',
            'Ana',
            'High',
            'Delivery Cycle 7',
            'Fix caching',
        ],
        [
            'OPS-4',
            'Worker retry',
            'Bug',
            'Done',
            'Done',
            'OPS',
            'Ana',
            'Bo',
            'High',
            'Delivery Cycle 8',
            'Retry jobs',
        ],
        [
            'APP-5',
            'Audit',
            'Task',
            'To Do',
            'To Do',
            'APP',
            'Bo',
            'Lee',
            'Urgent',
            'Delivery Cycle 7',
            'Audit events',
        ],
    ]:
        w.writerow(row)
    result = client.post('/api/imports', files={'file': ('context.csv', out.getvalue().encode(), 'text/csv')})
    assert result.status_code == 202
    return result.json()['id']


def ask(client, dataset, text, session=None, **kwargs):
    result = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={'message': text, 'session_id': session, 'mode': 'retrieval', **kwargs},
    )
    assert result.status_code == 200, result.text
    return result.json()


def keys(reply):
    return {s['key'] for s in reply['sources']}


def test_employee_priority_followup_persists_filters_across_resume_page_change_and_restart(client):
    dataset = upload(client)
    first = ask(client, dataset, 'Tell me about Ana work items', project='APP')
    assert first['conversation_context']['person']['name'] == 'Ana'
    follow = ask(
        client,
        dataset,
        'What are the high priority tickets?',
        first['session_id'],
        project='OPS',
        page='overview',
    )
    assert keys(follow) == {'APP-1', 'OPS-4'}
    assert follow['context_inherited'] is True
    assert (
        'Assignee: Ana' in follow['context_description'] and 'Priority: High' in follow['context_description']
    )
    assert '| Total tickets | 2 |' in follow['content']
    state = client.get(f'/api/datasets/{dataset}/agent/sessions/{first["session_id"]}').json()
    assert state['conversation_context']['person']['name'] == 'Ana'
    store.initialize()
    sprint = ask(client, dataset, 'Only those in sprint 7', first['session_id'])
    assert keys(sprint) == {'APP-1'}
    assert (
        'Priority: High' in sprint['context_description']
        and 'Delivery Cycle 7' in sprint['context_description']
    )
    assert all(s['key'] != 'APP-3' for s in sprint['sources'])


def test_subject_changes_broadening_clear_and_new_chat_are_independent(client):
    dataset = upload(client)
    original = ask(client, dataset, 'Tell me about Ana work items')
    high = ask(client, dataset, 'Show the high priority tickets', original['session_id'])
    assert keys(high) == {'APP-1', 'OPS-4'}
    any_priority = ask(client, dataset, 'Show tickets of all priorities', original['session_id'])
    assert keys(any_priority) == {'APP-1', 'APP-2', 'OPS-4'}
    assert any_priority['conversation_context']['person']['name'] == 'Ana'
    assert any_priority['conversation_context']['filters'] == []
    other = ask(client, dataset, 'Show Bo work items', original['session_id'])
    assert (
        other['conversation_context']['person']['name'] == 'Bo'
        and other['conversation_context']['filters'] == []
    )
    broad = ask(
        client, dataset, 'Show high priority tickets for everyone across all projects', original['session_id']
    )
    assert keys(broad) == {'APP-1', 'APP-3', 'OPS-4'} and broad['conversation_context']['person'] is None
    fresh = ask(client, dataset, 'Show high priority tickets', reset_context=True)
    assert fresh['session_id'] != original['session_id'] and fresh['conversation_context']['person'] is None
    # Returning to the old session retains its own scope independently.
    still = ask(client, dataset, 'Only bugs', original['session_id'])
    assert keys(still) == {'APP-3', 'OPS-4'}


def test_session_listing_and_message_pagination_preserve_all_turns_and_dataset_boundary(client):
    dataset = upload(client)
    foreign = upload(client)
    first = ask(client, dataset, 'Tell me about Ana work items')
    second = ask(client, dataset, 'Show Bo work items')
    listing = client.get(f'/api/datasets/{dataset}/agent/sessions', params={'limit': 1}).json()
    assert listing['has_more'] and listing['sessions'][0]['session_id'] == second['session_id']
    rest = client.get(f'/api/datasets/{dataset}/agent/sessions', params={'offset': 1}).json()
    assert rest['sessions'][0]['title'] == 'Tell me about Ana work items'
    assert client.get(f'/api/datasets/{foreign}/agent/sessions/{first["session_id"]}').status_code == 404
    assert not client.get(f'/api/datasets/{foreign}/agent/sessions').json()['sessions']
    from app.agent.history_store import append_messages

    append_messages(
        first['session_id'],
        [
            (
                'user' if n % 2 == 0 else 'assistant',
                {'content': f'History record {n}'},
                '2026-01-01T00:00:00+00:00',
            )
            for n in range(70)
        ],
    )
    page = client.get(f'/api/datasets/{dataset}/agent/sessions/{first["session_id"]}').json()
    assert len(page['messages']) == 60 and page['has_more']
    older = client.get(
        f'/api/datasets/{dataset}/agent/sessions/{first["session_id"]}',
        params={'before_id': page['before_id']},
    ).json()
    assert len(older['messages']) == 12 and not older['has_more']
    ids = [m['id'] for m in older['messages'] + page['messages']]
    assert len(set(ids)) == 72 and ids == sorted(ids)
    followup = ask(client, dataset, 'What are the high priority tickets?', first['session_id'])
    assert keys(followup) == {'APP-1', 'OPS-4'}


def test_context_constraints_apply_when_model_omits_person_or_uses_page_scope(client):
    dataset = upload(client)
    ctx = Context(dataset, 'OPS')
    state = conversation.resolve(ctx, 'Tell me about Ana work items')
    conversation.resolve(ctx, 'Show high priority tickets', state)
    result = ctx.call('query_metadata', {'project': 'OPS', 'filters': []})
    assert result['total'] == 2 and {t['assignee'] for t in result['tickets']} == {'Ana'}
    search = ctx.call('search_tickets', {'query': 'migration', 'project': None, 'sprint': None, 'limit': 6})
    assert {t['key'] for t in search['tickets']} == {'APP-1'}


def test_model_context_profiles_expand_history_excerpts_and_always_include_scope(client, monkeypatch):
    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'small')
    monkeypatch.setenv('JIRA_AI_MODELS', 'small,large')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://local/v1')
    monkeypatch.setenv('JIRA_AI_MODEL_CONTEXT_PROFILES', '{"small":"compact","large":"expanded"}')
    monkeypatch.setenv('JIRA_AI_MODEL_CONTEXT_WINDOWS', '{"small":32768,"large":40960}')
    requests = []
    original = httpx.Client

    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'APP-1 is in Testing.'}}]})

    monkeypatch.setattr(
        provider.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    history = [
        {'role': 'user' if n % 2 == 0 else 'assistant', 'content': 'Earlier context ' * 200}
        for n in range(50)
    ]
    for model in ('small', 'large'):
        ctx = Context(dataset)
        conversation.resolve(ctx, 'Explain APP-1')
        provider.run(ctx, 'Explain APP-1', history, [], connection_id='env:' + model)
        assert ctx.context_usage['history_messages'] > 0
    assert len(requests[1]['messages']) > len(requests[0]['messages'])

    def evidence(body):
        return json.loads(
            next(
                m['content']
                for m in body['messages']
                if m['content'].startswith('Application-retrieved ticket evidence')
            ).split('instructions): ', 1)[1]
        )

    assert len(evidence(requests[1])[0]['source_text']) > len(evidence(requests[0])[0]['source_text'])
    assert all(
        any(m['content'].startswith('Resolved conversation memory') for m in b['messages']) for b in requests
    )


def test_budget_prunes_whole_tool_rounds_without_orphan_calls():
    class Probe:
        pass

    ctx = Probe()
    ctx._history_count = 0
    ctx.context_usage = {'omitted_tool_rounds': 0}
    base = [
        {'role': 'system', 'content': 'Generic policy'},
        {'role': 'user', 'content': 'Resolved conversation memory: person and filters'},
        {'role': 'user', 'content': 'Current question'},
    ]
    rounds = []
    for n in range(3):
        rounds.extend(
            [
                {
                    'role': 'assistant',
                    'tool_calls': [{'id': str(n), 'function': {'name': 'get_ticket', 'arguments': '{}'}}],
                },
                {'role': 'tool', 'tool_call_id': str(n), 'content': 'x' * 13000},
            ]
        )
    fitted = context_budget.fit({'messages': base + rounds}, {'context_window': 16384}, ctx)['messages']
    calls = {c['id'] for m in fitted for c in m.get('tool_calls', [])}
    results = {m['tool_call_id'] for m in fitted if m.get('role') == 'tool'}
    assert calls == results and calls and len(calls) < 3
    assert any('Resolved conversation memory' in m.get('content', '') for m in fitted)


def test_verified_custom_filters_and_reporter_context_survive_followups(client):
    dataset = upload(client)
    ctx = Context(dataset)
    conversation.resolve(ctx, 'Show work assigned to Ana')
    ctx.call(
        'query_metadata', {'filters': [{'field': 'Summary', 'operator': 'contains', 'value': 'migration'}]}
    )
    saved = ctx.conversation_memory
    assert saved['filters'][0]['field'] == 'Summary'
    resumed = Context(dataset)
    conversation.resolve(resumed, 'Show those tickets', saved)
    data = resumed.call('query_metadata', {})
    assert {i['key'] for i in data['tickets']} == {'APP-1'}
    reporter = ask(client, dataset, 'Tell me about Ana work items')
    reported = ask(client, dataset, 'Show their reported tickets', reporter['session_id'])
    assert keys(reported) == {'APP-3'} and reported['conversation_context']['person']['field'] == 'reporter'


def test_connection_context_settings_are_validated_and_redacted(client):
    result = client.post(
        '/api/agent/connections',
        json={
            'name': 'Larger local model',
            'provider': 'compatible',
            'model': 'custom-large',
            'base': 'http://localhost:11434/v1',
            'context_profile': 'expanded',
            'context_window': 65536,
        },
    ).json()
    assert result['context_profile'] == 'expanded' and result['context_window'] == 65536
    choices = client.get('/api/agent/connections').json()['choices']
    assert choices[0]['context_profile'] == 'expanded' and choices[0]['context_window'] == 65536
    assert (
        client.post(
            '/api/agent/connections',
            json={
                'name': 'Invalid context',
                'provider': 'compatible',
                'model': 'x',
                'base': 'http://localhost:11434/v1',
                'context_window': 1024,
            },
        ).status_code
        == 422
    )
    assert context_budget.settings({'context_window': 65536})['profile'] == 'expanded'


def test_unknown_new_person_does_not_silently_fall_back_to_previous_person(client):
    dataset = upload(client)
    original = ask(client, dataset, 'Tell me about Ana work items')
    unknown = ask(client, dataset, 'Tell me about Taylor work items', original['session_id'])
    assert unknown['conversation_context']['person'] is None
    assert not unknown['sources'] and 'No exported assignee or reporter matches' in unknown['content']
    followup = ask(client, dataset, 'What are the high priority tickets?', original['session_id'])
    assert not followup['sources'] and 'Which exported assignee or reporter' in followup['content']


def test_workspace_history_identifies_original_import_without_cross_dataset_access(client):
    first = upload(client)
    second = upload(client)
    a = ask(client, first, 'Tell me about Ana work items')
    b = ask(client, second, 'Tell me about Bo work items')
    listing = client.get('/api/agent/conversations').json()['sessions']
    assert {i['dataset_id'] for i in listing} == {first, second}
    assert all(i['filename'] == 'context.csv' for i in listing)
    assert client.get(f'/api/datasets/{first}/agent/sessions/{b["session_id"]}').status_code == 404
    assert client.get(f'/api/datasets/{first}/agent/sessions/{a["session_id"]}').status_code == 200


def test_comparison_memory_does_not_silently_choose_the_last_person(client):
    dataset = upload(client)
    ctx = Context(dataset)
    conversation.resolve(ctx, 'Compare Ana and Bo tickets')
    ctx.call('employee_analysis', {'person': 'Ana'})
    ctx.call('employee_analysis', {'person': 'Bo'})
    ctx.call('query_metadata', {'filters': [{'field': 'assignee', 'operator': 'eq', 'value': 'Ana'}]})
    ctx.call('query_metadata', {'filters': [{'field': 'assignee', 'operator': 'eq', 'value': 'Bo'}]})
    assert ctx.conversation_memory['person'] is None and set(ctx.conversation_memory['candidates']) == {
        'Ana',
        'Bo',
    }
    follow = Context(dataset)
    conversation.resolve(follow, 'What are the high priority tickets?', ctx.conversation_memory)
    assert 'Which person' in follow.memory_clarification


def test_slow_or_incomplete_model_preserves_memory_without_substituting_a_report(client, monkeypatch):
    from app.agent import transport

    dataset = upload(client)
    first = ask(client, dataset, 'Tell me about Ana work items')
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'large')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://local/v1')

    def slow(*args, **kwargs):
        raise httpx.ReadTimeout('Simulated slow reasoning')

    monkeypatch.setattr(transport, 'request', slow)
    request = {'message': 'Tell me about Ana work items', 'session_id': first['session_id'], 'mode': 'ai'}
    reply = client.post(f'/api/datasets/{dataset}/agent/chat', json=request)
    assert reply.status_code == 502 and 'content' not in reply.json()

    def incomplete(*args, **kwargs):
        return {
            'choices': [{'finish_reason': 'length', 'message': {'content': 'unsupported generated claim'}}]
        }

    monkeypatch.setattr(transport, 'request', incomplete)
    reply = client.post(f'/api/datasets/{dataset}/agent/chat', json=request)
    assert reply.status_code == 502 and 'unsupported generated claim' not in reply.text
    history = client.get(f'/api/datasets/{dataset}/agent/sessions/{first["session_id"]}').json()
    assert len(history['messages']) == 2 and history['conversation_context']['person']['name'] == 'Ana'


def test_continuous_reasoning_stream_cannot_extend_request_indefinitely(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from app.agent import transport

    ticks = iter([0, 0, 91])
    monkeypatch.setattr(transport, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))

    class StreamingClient:
        @contextmanager
        def stream(self, *args, **kwargs):
            yield httpx.Response(
                200,
                request=httpx.Request('POST', 'http://local'),
                headers={'content-type': 'text/event-stream'},
                text='data: {"choices":[{"delta":{"reasoning":"private"}}]}\n\ndata: [DONE]\n\n',
            )

    events = []
    with pytest.raises(httpx.ReadTimeout):
        transport.request(
            StreamingClient(),
            'http://local',
            {},
            {},
            90,
            'chat',
            lambda event, data: events.append((event, data)),
        )
    assert all('private' not in str(data) for event, data in events)


def test_message_page_preferences_and_conversation_first_sprint_resolution(client):
    dataset = upload(client)
    first = ask(client, dataset, 'Summarize sprint 8', project='APP', sprint='Delivery Cycle 7')
    follow = ask(
        client,
        dataset,
        'Summarize this sprint',
        first['session_id'],
        project='APP',
        sprint='Delivery Cycle 7',
    )
    assert follow['scope']['sprint'] == 'Delivery Cycle 8'
    assert '| Total tickets | 1 |' in follow['content']
    fresh = ask(
        client,
        dataset,
        'Summarize this sprint',
        first['session_id'],
        reset_context=True,
        project='APP',
        sprint='Delivery Cycle 7',
    )
    assert fresh['scope']['sprint'] == 'Delivery Cycle 7'
    disabled = ask(
        client,
        dataset,
        'Summarize this sprint',
        project='APP',
        sprint='Delivery Cycle 7',
        use_page_context=False,
    )
    assert 'Which sprint' in disabled['content']
    assert disabled['page_hint']['enabled'] is False
    assert disabled['page_hint']['project'] == 'APP'
    explicit = ask(client, dataset, 'Summarize sprint 8', project='APP', use_page_context=False)
    assert explicit['scope']['sprint'] == 'Delivery Cycle 8'
    global_view = ask(client, dataset, 'Give me a project overview', project='APP', use_page_context=False)
    assert global_view['scope']['project'] == 'All projects'
    assert '| Total tickets | 5 |' in global_view['content']


def test_fresh_question_excludes_old_model_history_and_persists_a_prompt_boundary(client, monkeypatch):
    from app.agent import routes

    dataset = upload(client)
    original = ask(client, dataset, 'Tell me about Ana work items')
    captured = []

    def run(context, message, history, attachments, allow_web, connection_id):
        captured.append((message, history, context.project, context.sprint))
        return 'Verified fresh response.', []

    monkeypatch.setattr(routes.connections, 'resolve', lambda _: {'configured': True, 'model': 'test'})
    monkeypatch.setattr(provider, 'run', run)
    base = f'/api/datasets/{dataset}/agent/chat'
    for text, options in [
        ('Fresh question', {'reset_context': True}),
        ('Follow up fresh question', {}),
        ('Independent question', {'use_conversation_context': False}),
        ('Follow independent question', {}),
    ]:
        result = client.post(
            base,
            json={
                'message': text,
                'session_id': original['session_id'],
                'mode': 'ai',
                'project': 'APP',
                'sprint': 'Delivery Cycle 7',
                'use_page_context': False,
                **options,
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()['conversation_context']['person'] is None
    assert captured[0][1] == [] and captured[2][1] == []
    assert [m['content'] for m in captured[1][1] if m['role'] == 'user'] == ['Fresh question']
    assert [m['content'] for m in captured[3][1] if m['role'] == 'user'] == ['Independent question']
    assert all(project == '' and sprint == '' for _, _, project, sprint in captured)
    transcript = client.get(f'/api/datasets/{dataset}/agent/sessions/{original["session_id"]}').json()
    assert len(transcript['messages']) == 10
    assert transcript['messages'][0]['content'] == 'Tell me about Ana work items'


def test_topic_search_checks_page_then_full_resolved_scope_without_losing_filters(client, monkeypatch):
    from app.agent import index

    dataset = upload(client)
    ctx = Context(dataset, 'APP', 'Delivery Cycle 7')
    conversation.resolve(ctx, 'Find related work about authentication')
    calls = []

    def search(dataset_id, query, project, sprint, limit, issue_keys, cache):
        calls.append(issue_keys)
        return [
            {'key': i['key'], 'retrieval': 'Keyword match', 'excerpt': i['summary']}
            | {k: i[k] for k in ('summary', 'status', 'type', 'project_key')}
            for i in ctx.rows
            if i['key'] in issue_keys
        ][:limit]

    monkeypatch.setattr(index, 'hybrid_search', search)
    result = ctx.call('search_tickets', {'query': 'authentication', 'limit': 6})
    assert calls[0] == {'APP-1', 'APP-2', 'APP-3', 'APP-5'}
    assert calls[1] == {'APP-1', 'APP-2', 'APP-3', 'APP-5', 'OPS-4'}
    assert {i['key'] for i in result['tickets']} == calls[1]
    conversation.resolve(ctx, 'Show Ana high priority tickets')
    calls.clear()
    ctx.call('search_tickets', {'query': 'authentication', 'limit': 6})
    assert all(keys <= {'APP-1', 'OPS-4'} for keys in calls)


def test_sprint_report_replaces_person_filters_but_person_followups_keep_them(client):
    dataset = upload(client)
    person = ask(client, dataset, 'Tell me about Ana work items', project='APP')
    high = ask(client, dataset, 'Show high priority tickets', person['session_id'])
    assert high['conversation_context']['person']['name'] == 'Ana'
    report = ask(client, dataset, 'Give me a report of sprint 7', person['session_id'], project='OPS')
    state = report['conversation_context']
    assert state['person'] is None and state['filters'] == []
    assert state['sprint'] == 'Delivery Cycle 7' and state['project'] == 'APP'
    assert state['last_intent'] == 'sprint'
    assert '| Total tickets | 4 |' in report['content']
    assert 'Assignee:' not in report['context_description']
    follow = ask(client, dataset, 'no i meant like in general overall', report['session_id'])
    assert follow['conversation_context']['person'] is None
    assert follow['conversation_context']['sprint'] == 'Delivery Cycle 7'
    resumed = client.get(f'/api/datasets/{dataset}/agent/sessions/{report["session_id"]}').json()
    assert resumed['conversation_context']['person'] is None
    ctx = Context(dataset)
    state = conversation.resolve(ctx, 'Tell me about Ana work items')
    state = conversation.resolve(ctx, 'Summarize his work in sprint 7', state)
    assert state['person']['name'] == 'Ana'
    assert ctx.call('sprint_summary', {})['metrics']['total'] == 2
    state = conversation.resolve(ctx, 'What are the high priority tickets?', state)
    assert state['person']['name'] == 'Ana' and ctx.call('query_metadata', {})['total'] == 1


def test_overall_correction_repairs_legacy_scope_and_rejects_reintroduced_person(client):
    dataset = upload(client)
    ctx = Context(dataset, 'OPS', 'Delivery Cycle 8')
    legacy = {
        **conversation.empty(),
        'person': {'name': 'Ana', 'field': 'assignee'},
        'project': 'APP',
        'sprint': 'Delivery Cycle 7',
        'filters': [{'field': 'type', 'operator': 'eq', 'value': 'Story'}],
        'ticket_set': ['APP-1'],
        'topic': 'old topic',
        'focus': 'person',
    }
    state = conversation.resolve(ctx, 'no i meant like in general overall', legacy)
    assert state['person'] is None and not state['filters'] and not state['ticket_set'] and not state['topic']
    assert state['sprint'] == 'Delivery Cycle 7' and state['project'] == 'APP'
    assert 'error' in ctx.call('employee_analysis', {'person': 'Ana'})
    assert 'error' in ctx.call(
        'query_metadata', {'filters': [{'field': 'Assignee', 'operator': 'eq', 'value': 'Ana'}]}
    )
    assert 'error' in ctx.call('project_summary', {})
    # Targeted subanalysis is permitted without becoming the next message's persistent filter.
    assert (
        ctx.call('query_metadata', {'filters': [{'field': 'priority', 'operator': 'eq', 'value': 'High'}]})[
            'total'
        ]
        == 2
    )
    assert not state['filters'] and state['person'] is None
    result = ctx.call('sprint_summary', {})
    assert result['metrics']['total'] == 4
    assert state['sprint'] == 'Delivery Cycle 7' and not state['filters']
    assert ctx.call('query_metadata', {})['total'] == 4
    # A later explicit request can deliberately narrow the conversation again.
    conversation.resolve(ctx, 'Now show Ana tickets', state)
    assert ctx.call('employee_analysis', {'person': 'Ana'})['assigned_tickets'] == 2


def test_new_topic_clears_person_and_stream_sends_resolved_memory_before_answer(client):
    dataset = upload(client)
    ctx = Context(dataset)
    state = conversation.resolve(ctx, 'Tell me about Ana work items')
    state = conversation.resolve(ctx, 'what is provider taxonomy', state)
    assert state['person'] is None and state['topic'] == 'provider taxonomy'
    assert not ctx.context_filters and state['ticket_set'] == []
    first = ask(client, dataset, 'Tell me about Ana work items', project='APP')
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'Give me a report of sprint 7',
            'session_id': first['session_id'],
            'mode': 'retrieval',
            'stream': True,
        },
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    initial = next(i for i, event in enumerate(events) if event['event'] == 'context')
    text = next(i for i, event in enumerate(events) if event['event'] == 'text_delta')
    assert initial < text
    assert events[initial]['conversation_context']['person'] is None
    assert events[initial]['conversation_context']['sprint'] == 'Delivery Cycle 7'
    assert 'Assignee:' not in events[initial]['context_description']
