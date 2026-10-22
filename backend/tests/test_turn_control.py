import concurrent.futures
import json
import threading

import pytest
from app.agent import connections, provider, turn_control
from fastapi import HTTPException
from test_conversations import client as context_client
from test_conversations import upload

client = context_client


def test_turn_inbox_safe_points_limit_and_idempotency():
    turn = turn_control.register('test-run', 'export-a')
    try:
        assert turn_control.find('test-run', 'export-a') is turn
        for i in range(4):
            assert turn.add({'id': str(i), 'message': f'Question {i}'})['count'] == i + 1
        assert turn.add({'id': '0', 'message': 'Question 0'})['count'] == 4
        with pytest.raises(HTTPException) as limit:
            turn.add({'id': 'fifth', 'message': 'Too many'})
        assert limit.value.status_code == 429
        with pytest.raises(turn_control.Steered):
            turn.checkpoint()
        assert len(turn.snapshot()) == 4
        turn.checkpoint()
        turn.seal()
        with pytest.raises(HTTPException) as sealed:
            turn.add({'id': 'late', 'message': 'Later'})
        assert sealed.value.status_code == 409
        with pytest.raises(HTTPException):
            turn_control.find('test-run', 'export-b')
    finally:
        turn_control.remove('test-run')


def test_stream_steers_at_boundary_and_persists_all_questions(client, monkeypatch):
    dataset = upload(client)
    client.post(f'/api/datasets/{dataset}/agent/index')
    monkeypatch.setattr(
        connections, 'resolve', lambda _: {'configured': True, 'model': 'test-selected-model'}
    )
    entered, release = threading.Event(), threading.Event()
    entered_again, release_again = threading.Event(), threading.Event()
    calls = []

    def respond(context, question, history, attachments, *args):
        calls.append((question, context.request_offset, context.action_offset, history))
        if len(calls) == 1:
            context.model_requests = 2
            context.actions_taken = 1
            entered.set()
            assert release.wait(5)
            context.checkpoint()
            pytest.fail('The original run must halt at its next boundary.')
        if len(calls) == 2:
            assert 'Follow-up 0' in question
            assert context.request_offset == 2 and context.action_offset == 1
            context.model_requests = 3
            context.actions_taken = 2
            entered_again.set()
            assert release_again.wait(5)
            context.checkpoint()
            pytest.fail('New steering must also halt a restarted response.')
        assert all(f'Follow-up {i}' in question for i in range(4))
        assert context.request_offset == 3 and context.action_offset == 2
        context.emit('text_delta', {'text': 'All requested questions considered.'})
        return 'All requested questions considered.', []

    monkeypatch.setattr(provider, 'run', respond)
    url = f'/api/datasets/{dataset}/agent/chat'
    with concurrent.futures.ThreadPoolExecutor() as pool:
        response = pool.submit(
            client.post,
            url,
            json={'message': 'Original request', 'stream': True, 'request_id': 'steering-test'},
        )
        assert entered.wait(5)
        for i in range(4):
            if i == 1:
                release.set()
                assert entered_again.wait(5)
            result = client.post(
                url + '/steering-test/steer', json={'id': str(i), 'message': f'Follow-up {i}'}
            )
            assert result.status_code == 200, result.text
        assert len(calls) == 2
        assert (
            client.post(url + '/steering-test/steer', json={'id': '5', 'message': 'Fifth'}).status_code == 429
        )
        release_again.set()
        result = response.result(timeout=10)
    events = [json.loads(line) for line in result.text.splitlines()]
    assert len(calls) == 3
    assert len([e for e in events if e['event'] == 'steering']) == 2
    done = next(e for e in events if e['event'] == 'done')
    saved = client.get(f'/api/datasets/{dataset}/agent/sessions/{done["session_id"]}').json()['messages']
    assert [m['content'] for m in saved] == [
        'Original request',
        *[f'Follow-up {i}' for i in range(4)],
        'All requested questions considered.',
    ]
    assert 'steering-test' not in turn_control.RUNS
    assert (
        client.post(url + '/steering-test/steer', json={'id': 'late', 'message': 'Later'}).status_code == 409
    )
    # Queued requests can start immediately and see the final conversation history.
    monkeypatch.setattr(provider, 'run', lambda context, question, history, *args: ('Next response', []))
    next_response = client.post(
        url, json={'message': 'Next request', 'session_id': done['session_id'], 'stream': True}
    )
    assert next_response.status_code == 200
    assert 'Next response' in next_response.text


def test_provider_stops_after_model_request_before_running_new_tools(client, monkeypatch):
    from app.agent import transport
    from app.agent.tools import Context

    dataset = upload(client)
    client.post(f'/api/datasets/{dataset}/agent/index')
    turn = turn_control.Turn(dataset)
    context = Context(dataset)
    context.checkpoint = turn.checkpoint
    monkeypatch.setattr(
        provider,
        'resolve',
        lambda _: {
            'configured': True,
            'provider': 'compatible',
            'model': 'selected-model',
            'base': 'http://127.0.0.1:11434/v1',
            'key': '',
            'web_available': False,
        },
    )
    requests = []

    def request(*args):
        requests.append(args[3])
        turn.add({'id': 'correction', 'message': 'Actually include the whole sprint.'})
        return {
            'choices': [
                {
                    'message': {
                        'content': '',
                        'tool_calls': [
                            {
                                'id': 'plan-1',
                                'type': 'function',
                                'function': {'name': 'plan_investigation', 'arguments': '{}'},
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr(transport, 'request', request)
    with pytest.raises(turn_control.Steered):
        provider.run(context, 'Review sprint 7', [], [])
    assert len(requests) == 1 and context.model_requests == 1
    assert not context.trace
