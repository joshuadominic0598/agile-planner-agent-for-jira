"""SSE transports: stream final-answer text and observable progress, never private reasoning."""

import json
import re
import time

import httpx


def clean_answer(text):
    return re.sub(r'<think>.*?(?:</think>|$)', '', text, flags=re.S | re.I).strip()


class VisibleText:
    def __init__(self):
        self.buffer = ''
        self.hidden = False

    def feed(self, text, final=False):
        self.buffer += text
        visible = ''
        while self.buffer:
            marker = '</think>' if self.hidden else '<think>'
            found = self.buffer.lower().find(marker)
            if found >= 0:
                if not self.hidden:
                    visible += self.buffer[:found]
                self.buffer = self.buffer[found + len(marker) :]
                self.hidden = not self.hidden
                continue
            keep = (
                0
                if final
                else max(
                    (n for n in range(1, len(marker)) if self.buffer.lower().endswith(marker[:n])), default=0
                )
            )
            if not self.hidden:
                visible += self.buffer[:-keep] if keep else self.buffer
            self.buffer = self.buffer[-keep:] if keep else ''
            break
        return visible


def _request(client, url, headers, body, timeout, kind, emit=None):
    if emit is None:
        response = client.post(url, headers=headers, json=body, timeout=timeout)
        response.raise_for_status()
        return response.json()
    deadline = time.monotonic() + timeout
    emit('answer_start', {})
    request_body = {**body, 'stream': True}
    if kind == 'chat' and 'api.openai.com' in url:
        request_body['stream_options'] = {'include_usage': True}
    with client.stream('POST', url, headers=headers, json=request_body, timeout=timeout) as response:
        response.raise_for_status()
        if 'text/event-stream' not in response.headers.get('content-type', ''):
            response.read()
            data = response.json()
            text = data.get('choices', [{}])[0].get('message', {}).get('content') if kind == 'chat' else None
            if isinstance(text, str):
                emit('text_delta', {'text': clean_answer(text)})
            return data
        content = ''
        visible = VisibleText()
        calls = {}
        finish = None
        seen_end = False
        progress = False
        output = []
        response_data = None
        extra_content = None
        reported_usage = None
        for line in response.iter_lines():
            if time.monotonic() > deadline:
                raise httpx.ReadTimeout('The model exceeded its streaming request time limit.')
            if not line.startswith('data:'):
                continue
            value = line[5:].strip()
            if value == '[DONE]':
                seen_end = True
                break
            if not value:
                continue
            item = json.loads(value)
            if item.get('usage'):
                reported_usage = item['usage']
            if kind == 'responses':
                event = item.get('type', '')
                if event == 'response.output_text.delta':
                    emit('text_delta', {'text': item.get('delta', '')})
                elif event.startswith('response.reasoning') and not progress:
                    emit('activity', {'message': 'Model is analyzing the retrieved evidence.'})
                    progress = True
                elif event == 'response.output_item.done':
                    output.append(item['item'])
                elif event in {'response.completed', 'response.incomplete', 'response.failed'}:
                    response_data = item.get('response', {})
                    seen_end = True
                elif event == 'error':
                    raise ValueError('Model stream reported an error. Retry the question.')
                continue
            if 'error' in item:
                raise ValueError('Model stream reported an error. Retry the question.')
            for choice in item.get('choices', []):
                delta = choice.get('delta') or {}
                if 'extra_content' in delta:
                    extra_content = delta['extra_content']
                if (delta.get('reasoning') or delta.get('reasoning_content')) and not progress:
                    emit('activity', {'message': 'Model is analyzing the retrieved evidence.'})
                    progress = True
                if isinstance(delta.get('content'), str):
                    text = visible.feed(delta['content'])
                    content += text
                    if text:
                        emit('text_delta', {'text': text})
                for fragment in delta.get('tool_calls') or []:
                    i = fragment.get('index', 0)
                    call = calls.setdefault(
                        i, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}}
                    )
                    if fragment.get('id'):
                        call['id'] = fragment['id']
                    function = fragment.get('function') or {}
                    call['function']['name'] += function.get('name') or ''
                    call['function']['arguments'] += function.get('arguments') or ''
                    if 'extra_content' in fragment:
                        call['extra_content'] = fragment['extra_content']
                if choice.get('finish_reason'):
                    finish = choice['finish_reason']
                    seen_end = True
        if not seen_end:
            raise ValueError('Model stream ended before completion. Retry the question.')
        if kind == 'responses':
            data = response_data or {'output': output}
            if not data.get('output'):
                data['output'] = output
            return data
        tail = visible.feed('', final=True)
        if tail:
            content += tail
            emit('text_delta', {'text': tail})
        return {
            **({'usage': reported_usage} if reported_usage else {}),
            'choices': [
                {
                    'message': {
                        'role': 'assistant',
                        'content': content,
                        'tool_calls': [calls[i] for i in sorted(calls)],
                        **({'extra_content': extra_content} if extra_content is not None else {}),
                    },
                    'finish_reason': finish,
                }
            ],
        }


def request(client, url, headers, body, timeout, kind, emit=None):
    from ..observability.telemetry import CURRENT

    trace = CURRENT.get()
    if trace is None:
        return _request(client, url, headers, body, timeout, kind, emit)
    return trace.model(
        lambda observed: _request(client, url, headers, body, timeout, kind, observed), body, emit
    )
