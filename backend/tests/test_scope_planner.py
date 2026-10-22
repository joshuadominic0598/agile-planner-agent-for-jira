import json

import pytest
from app.agent import context_budget, conversation, scope_planner, transport
from app.agent.scope_planner import rebuild as rebuild_scope
from app.agent.tools import Context
from test_conversations import ask, upload
from test_conversations import client as context_client

client = context_client


def plan(**changes):
    return scope_planner.Plan(
        intent='sprint',
        mode='replace',
        project='APP',
        sprint='7',
        summary='Review the whole sprint, across all assignees.',
        **changes,
    )


def test_ai_context_replaces_person_but_retains_report_sprint_and_ignores_page(client):
    dataset = upload(client)
    context = Context(dataset, 'OPS', 'Delivery Cycle 8')
    old = {
        **conversation.empty(),
        'person': {'name': 'Ana', 'field': 'assignee'},
        'project': 'APP',
        'sprint': 'Delivery Cycle 7',
        'focus': 'person',
        'ticket_set': ['APP-1'],
        'filters': [{'field': 'priority', 'operator': 'eq', 'value': 'High'}],
    }
    conversation.resolve(context, 'no, I mean everyone in that iteration', old)
    scope_planner.apply(context, plan())
    assert context.conversation_memory['person'] is None
    assert not context.context_filters and not context.conversation_memory['ticket_set']
    assert context.conversation_memory['working_summary'] == 'Review the whole sprint, across all assignees.'
    assert context.call('sprint_summary', {})['metrics']['total'] == 4
    conversation.resolve(context, 'Show Ana high priority tickets in sprint 7', context.conversation_memory)
    scope_planner.apply(
        context,
        scope_planner.Plan(
            intent='lookup',
            mode='refine',
            project='APP',
            sprint='7',
            person='Ana',
            filters=[{'field': 'priority', 'operator': 'eq', 'value': 'High'}],
            summary='Show Ana’s high-priority sprint tickets.',
        ),
    )
    assert context.call('query_metadata', {})['total'] == 1


def test_scope_planner_validates_names_identifiers_and_ambiguity(client):
    dataset = upload(client)
    context = Context(dataset)
    conversation.resolve(context, 'Give me a report of APP sprint 7')
    with pytest.raises(ValueError, match='explicit sprint'):
        scope_planner.apply(
            context,
            scope_planner.Plan(
                intent='sprint', mode='replace', project='APP', sprint=None, summary='Wrong scope'
            ),
        )
    with pytest.raises(ValueError, match='project'):
        scope_planner.apply(
            context,
            scope_planner.Plan(intent='project', mode='replace', project='invented', summary='Wrong project'),
        )
    scope_planner.apply(
        context,
        scope_planner.Plan(
            intent='clarify',
            mode='clarify',
            summary='The intended person is unclear.',
            clarification='Do you mean Ana or Bo?',
        ),
    )
    assert context.clarification_needed and context.memory_clarification == 'Do you mean Ana or Bo?'


@pytest.mark.parametrize('adapter', ['compatible', 'openai', 'gemini'])
def test_selected_model_rebuilds_context_with_bounded_evidence_and_safe_fallback(
    client, monkeypatch, adapter
):
    dataset = upload(client)
    context = Context(dataset)
    old = conversation.resolve(context, 'Tell me about Ana work items')
    conversation.resolve(context, 'Give me a report of sprint 7', old)
    cfg = {
        'provider': adapter,
        'configured': True,
        'model': 'selected-model',
        'base': 'http://selected/v1',
        'key': 'synthetic-key',
        'context_window': 8192,
    }
    bodies = []

    def request(client, url, headers, body, timeout, protocol, emit=None):
        bodies.append(body)
        assert body['model'] == 'selected-model'
        assert context_budget.estimate(body) < 8192 - body.get('max_output_tokens', body.get('max_tokens'))
        text = json.dumps(plan().model_dump())
        return (
            {'choices': [{'message': {'content': text}}]}
            if protocol == 'chat'
            else {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
        )

    monkeypatch.setattr(transport, 'request', request)
    rebuild_scope(
        context, context.question, old, [{'role': 'user', 'content': 'Tell me about Ana work items'}], cfg
    )
    assert context.memory_model_requests == 1 and len(bodies) == 1
    assert context.conversation_memory['memory_source'] == 'selected_model'
    assert context.conversation_memory['person'] is None
    assert context.call('sprint_summary', {})['metrics']['total'] == 4
    monkeypatch.setattr(
        transport, 'request', lambda *args: {'choices': [{'message': {'content': 'not valid context'}}]}
    )
    fallback = Context(dataset)
    conversation.resolve(fallback, 'Give me a report of sprint 7', old)
    rebuild_scope(fallback, fallback.question, old, [], cfg)
    assert not fallback.trace[-1]['ok']
    assert fallback.conversation_memory['person'] is None


def test_real_planner_stage_streams_new_context_and_persists_it_without_stale_person(client, monkeypatch):
    dataset = upload(client)
    first = ask(client, dataset, 'Tell me about Ana work items', project='APP')
    monkeypatch.setattr(scope_planner, 'rebuild', rebuild_scope)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'selected-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://selected/v1')
    calls = []

    def request(client, url, headers, body, timeout, protocol, emit=None):
        calls.append(body)
        if len(calls) == 1:
            text = json.dumps(plan().model_dump())
        elif len(calls) == 2:
            return {
                'choices': [
                    {
                        'message': {
                            'tool_calls': [
                                {
                                    'id': 'plan',
                                    'type': 'function',
                                    'function': {
                                        'name': 'plan_investigation',
                                        'arguments': json.dumps(
                                            {
                                                'intent': 'Review full sprint',
                                                'retrieval': 'metadata',
                                                'steps': ['Query full sprint'],
                                            }
                                        ),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        elif len(calls) == 3:
            return {
                'choices': [
                    {
                        'message': {
                            'tool_calls': [
                                {
                                    'id': 'summary',
                                    'type': 'function',
                                    'function': {
                                        'name': 'sprint_summary',
                                        'arguments': json.dumps({'sprint': '7', 'project': 'APP'}),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        else:
            text = 'The sprint contains 4 tickets assigned to Ana and Bo.'
        return {'choices': [{'message': {'content': text}}]}

    monkeypatch.setattr(transport, 'request', request)
    response = client.post(
        f'/api/datasets/{dataset}/agent/chat',
        json={
            'message': 'Give me a report of sprint 7',
            'session_id': first['session_id'],
            'mode': 'ai',
            'stream': True,
            'project': 'OPS',
            'sprint': 'Delivery Cycle 8',
        },
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['event'] == 'done', events[-1]
    resolved = next(event for event in events if event['event'] == 'context')
    assert resolved['conversation_context']['person'] is None
    assert resolved['conversation_context']['sprint'] == 'Delivery Cycle 7'
    assert events[-1]['conversation_context']['memory_source'] == 'selected_model'
    assert events[-1]['investigation']['model_requests'] == len(calls) == 4
    assert events[-1]['scope'] == {'project': 'APP', 'sprint': 'Delivery Cycle 7'}
    assert any(t['tool'] == 'update_context' and t['ok'] for t in events[-1]['tools'])
    resumed = client.get(f'/api/datasets/{dataset}/agent/sessions/{first["session_id"]}').json()
    assert resumed['conversation_context']['person'] is None
    assert resumed['conversation_context']['working_summary'] == plan().summary
    assert resumed['context_description'] == events[-1]['context_description']


def test_context_update_is_not_grounding_and_quota_does_not_retry(client, monkeypatch):
    import httpx
    from app.agent import provider

    dataset = upload(client)
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'compatible')
    monkeypatch.setenv('JIRA_AI_MODEL', 'selected-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://selected/v1')
    context = Context(dataset)
    conversation.resolve(context, 'Report sprint 7')
    context.trace.append({'tool': 'update_context', 'ok': True, 'result_count': 0})
    monkeypatch.setattr(
        transport, 'request', lambda *args: {'choices': [{'message': {'content': 'An unverified report.'}}]}
    )
    with pytest.raises(provider.ModelError, match='not retrieve evidence'):
        provider.run(context, context.question, [], [])
    calls = []

    def quota(*args):
        calls.append(True)
        response = httpx.Response(429, request=httpx.Request('POST', 'http://selected/v1/chat/completions'))
        response.raise_for_status()

    monkeypatch.setattr(transport, 'request', quota)
    with pytest.raises(provider.ModelError, match='quota reached while updating context'):
        rebuild_scope(
            context,
            context.question,
            None,
            [],
            {
                'provider': 'compatible',
                'model': 'selected-model',
                'base': 'http://selected/v1',
                'key': '',
                'context_window': 32768,
            },
        )
    assert len(calls) == 1
