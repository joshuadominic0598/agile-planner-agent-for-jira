"""Bounded per-run model/tool traces. Credentials and private reasoning are excluded."""

import contextvars
import functools
import json
import math
import re
import time
import uuid
from datetime import datetime, timezone

from .. import store
from . import langfuse_bridge, pricing

CURRENT = contextvars.ContextVar('agent_trace', default=None)
SECRET = re.compile(r'(?:sk-[\w-]{12,}|AIza[\w-]{20,}|Bearer\s+[\w.\-]{12,})', re.I)


def clean(value, limit=24000):
    def sanitize(item):
        if isinstance(item, dict):
            return {
                k: (
                    '[redacted]'
                    if k.casefold()
                    in {
                        'api_key',
                        'authorization',
                        'secret',
                        'password',
                        'reasoning_content',
                        'thought_signature',
                    }
                    else sanitize(v)
                )
                for k, v in item.items()
            }
        if isinstance(item, list):
            return [sanitize(v) for v in item]
        if isinstance(item, str):
            return re.sub(r'<think>.*?(?:</think>|$)', '[private reasoning omitted]', item, flags=re.S | re.I)
        return item

    safe = sanitize(value)
    text = safe if isinstance(safe, str) else json.dumps(safe, ensure_ascii=False, default=str)
    return SECRET.sub('[redacted credential]', text)[:limit]


def payload(value, limit=20000):
    text = clean(value, limit)
    try:
        return json.loads(text)
    except ValueError:
        return {'preview': text, 'truncated': True}


def now():
    return datetime.now(timezone.utc).isoformat()


def tokens(text):
    return math.ceil(len((text if isinstance(text, str) else json.dumps(text, default=str)).encode()) / 4)


def usage(data, body, output):
    u = data.get('usage') or data.get('usageMetadata') or {}
    inp = u.get('input_tokens', u.get('prompt_tokens', u.get('promptTokenCount')))
    out = u.get('output_tokens', u.get('completion_tokens', u.get('candidatesTokenCount')))
    return {
        'input_tokens': inp if inp is not None else tokens(body),
        'output_tokens': out if out is not None else tokens(output),
        'cached_input_tokens': (u.get('input_tokens_details') or u.get('prompt_tokens_details') or {}).get(
            'cached_tokens', u.get('cachedContentTokenCount', 0)
        ),
        'reasoning_tokens': (u.get('output_tokens_details') or u.get('completion_tokens_details') or {}).get(
            'reasoning_tokens', u.get('thoughtsTokenCount', 0)
        ),
        'source': 'provider' if inp is not None and out is not None else 'estimated',
        'input_source': 'provider' if inp is not None else 'estimated',
        'output_source': 'provider' if out is not None else 'estimated',
    }


def output_text(data):
    if data.get('choices'):
        m = data['choices'][0].get('message') or {}
        return str(m.get('content') or '') + json.dumps(m.get('tool_calls') or [])
    return ''.join(
        p.get('text', '')
        for o in data.get('output', [])
        for p in o.get('content', [])
        if p.get('type') == 'output_text'
    )


class Trace:
    def __init__(self, dataset, session, cfg, question, request_id=None, kind='chat', page=None):
        self.id = request_id if request_id and re.fullmatch('[a-f0-9]{32}', request_id) else uuid.uuid4().hex
        self.started = time.monotonic()
        self.first_token = None
        self.events, self.models, self.tools, self.evidence = [], [], [], []
        self.cfg = cfg
        self.doc = {
            'id': self.id,
            'dataset_id': dataset,
            'session_id': session,
            'kind': kind,
            'status': 'running',
            'started_at': now(),
            'updated_at': now(),
            'question': clean(question, 20000),
            'model': cfg.get('model', ''),
            'provider': cfg.get('provider', ''),
            'page': page or {},
            'feedback': {},
            'model_calls': [],
            'tool_calls': [],
            'events': [],
            'usage': {},
            'context': {},
            'cost_usd': None,
        }
        self.root = None
        self.lf_error = ''
        try:
            self.root = langfuse_bridge.start(
                self.id,
                session,
                'Sprint Agent',
                'agent',
                {'question': self.doc['question'], 'page': page or {}},
            )
        except Exception as exc:
            self.lf_error = type(exc).__name__
        store.mongo().agent_runs.insert_one(self.doc.copy())
        self.token = CURRENT.set(self)

    def persist(self, **changes):
        if 'model_calls' in changes:
            changes['model_call_count'] = len(self.models)
            changes['usage'] = {
                'input_tokens': sum(m.get('usage', {}).get('input_tokens', 0) for m in self.models),
                'output_tokens': sum(m.get('usage', {}).get('output_tokens', 0) for m in self.models),
                'estimated_calls': sum(m.get('usage', {}).get('source') == 'estimated' for m in self.models),
            }
        if 'tool_calls' in changes:
            changes['tool_call_count'] = len(self.tools)
        self.doc.update(changes, updated_at=now())
        store.mongo().agent_runs.update_one(
            {'id': self.id}, {'$set': changes | {'updated_at': self.doc['updated_at']}}
        )

    def event(self, event, data):
        if event == 'text_delta':
            if self.first_token is None and data.get('text'):
                self.first_token = time.monotonic() - self.started
            return
        if event in {'context', 'steering', 'activity'}:
            self.events.append(
                {
                    'event': event,
                    'at_ms': round((time.monotonic() - self.started) * 1000),
                    'data': clean(data, 3500),
                }
            )
            if event == 'context':
                self.doc['context']['conversation'] = payload(data, 20000)
            self.persist(events=self.events[-150:], context=self.doc['context'])

    def model(self, invoke, body, emit):
        started = time.monotonic()
        generation = None
        entry = {
            'index': len(self.models) + 1,
            'started_at': now(),
            'model': body.get('model', self.cfg.get('model')),
            'input_chars': len(json.dumps(body)),
            'input': clean(body),
            'status': 'running',
        }
        self.models.append(entry)
        self.persist(model_calls=self.models)
        try:
            generation = langfuse_bridge.start(
                self.id,
                self.doc['session_id'],
                'model request',
                'generation',
                entry['input'],
                self.root.id if self.root else None,
                entry['model'],
            )
        except Exception as exc:
            self.lf_error = type(exc).__name__
        partial = []

        def observed(event, data):
            if event == 'text_delta':
                partial.append(str(data.get('text', '')))
            if emit:
                emit(event, data)

        result = {}
        try:
            result = invoke(observed if emit else None)
            entry['status'] = 'success'
            return result
        except Exception as exc:
            entry.update(status='error', error=clean(str(exc), 500))
            raise
        finally:
            text = output_text(result) if result else ''.join(partial)
            u = usage(result, body, text)
            try:
                overrides = store.mongo().workspace_settings.find_one({'id': 'pricing'}, {'_id': 0}) or {}
                cost = pricing.estimate(
                    entry['model'],
                    self.cfg.get('provider'),
                    u,
                    body.get('service_tier', 'default'),
                    overrides.get('rates'),
                    self.cfg.get('base', ''),
                )
            except Exception:
                cost = {'usd': None, 'priced': False, 'basis': 'rate lookup unavailable'}
            entry.update(
                latency_ms=round((time.monotonic() - started) * 1000), usage=u, cost=cost, output=clean(text)
            )
            self.persist(model_calls=self.models)
            if generation:
                try:
                    generation.update(
                        output=entry['output'],
                        usage_details={'input': u['input_tokens'], 'output': u['output_tokens']},
                        cost_details={'total': cost['usd']} if cost['usd'] is not None else None,
                        level='ERROR' if entry['status'] == 'error' else 'DEFAULT',
                    )
                    generation.end()
                except Exception as exc:
                    self.lf_error = type(exc).__name__

    def external_model(self, body, data, elapsed, status='success'):
        text = output_text(data)
        u = usage(data, body, text)
        override = store.mongo().workspace_settings.find_one({'id': 'pricing'}) or {}
        cost = pricing.estimate(
            body.get('model', self.cfg['model']),
            self.cfg.get('provider'),
            u,
            overrides=override.get('rates'),
            base=self.cfg.get('base', ''),
        )
        entry = {
            'index': len(self.models) + 1,
            'model': body.get('model'),
            'started_at': now(),
            'status': status,
            'input_chars': len(json.dumps(body)),
            'input': clean(body),
            'output': clean(text),
            'latency_ms': round(elapsed * 1000),
            'usage': u,
            'cost': cost,
        }
        self.models.append(entry)
        self.persist(model_calls=self.models)
        try:
            span = langfuse_bridge.start(
                self.id,
                self.doc['session_id'],
                'evaluation model',
                'generation',
                entry['input'],
                self.root.id if self.root else None,
                entry['model'],
            )
            if span:
                span.update(
                    output=entry['output'],
                    usage_details={'input': u['input_tokens'], 'output': u['output_tokens']},
                    cost_details={'total': cost['usd']} if cost['usd'] is not None else None,
                )
                span.end()
        except Exception as exc:
            self.lf_error = type(exc).__name__

    def tool(self, name, args, result, elapsed, error='', cached=False):
        serialized = json.dumps(result, default=str)

        def chunks(value):
            found = []
            if isinstance(value, dict):
                for key, item in value.items():
                    if (
                        key in {'excerpt', 'source_text', 'content', 'quote'}
                        and isinstance(item, str)
                        and item.strip()
                    ):
                        found.append(item)
                    elif isinstance(item, (dict, list)):
                        found.extend(chunks(item))
            elif isinstance(value, list):
                for item in value[:100]:
                    found.extend(chunks(item))
            return found

        extracted = chunks(result)
        self.evidence.extend(extracted)
        self.evidence = list(dict.fromkeys(self.evidence))[:100]
        entry = {
            'tool': name,
            'cached': cached,
            'arguments': payload(args, 8000),
            'latency_ms': round(elapsed * 1000),
            'ok': not bool(error),
            'error': clean(error, 500),
            'result_chars': len(serialized),
            'chunks_returned': len(extracted),
            'result': clean(serialized, 18000),
        }
        self.tools.append(entry)
        self.persist(
            tool_calls=self.tools[-100:],
            retrieved_contexts=[clean(t, 3500) for t in self.evidence],
            context={
                'conversation': self.doc['context'].get('conversation'),
                'chunks_returned': sum(t['chunks_returned'] for t in self.tools),
                'unique_chunks': len(self.evidence),
                'retrieved_chars': sum(map(len, self.evidence)),
                'average_chunk_chars': round(sum(map(len, self.evidence)) / len(self.evidence))
                if self.evidence
                else 0,
            },
        )
        try:
            span = langfuse_bridge.start(
                self.id,
                self.doc['session_id'],
                name,
                'retriever' if name in {'search_tickets', 'investigate_tickets', 'explore_graph'} else 'tool',
                entry['arguments'],
                self.root.id if self.root else None,
            )
            if span:
                span.update(
                    output=entry['result'],
                    metadata={'latency_ms': entry['latency_ms'], 'chunks_returned': len(extracted)},
                    level='ERROR' if error else 'DEFAULT',
                )
                span.end()
        except Exception as exc:
            self.lf_error = type(exc).__name__

    def finish(self, status, result=None, error=''):
        result = result or {}
        elapsed = time.monotonic() - self.started
        inp = sum(m.get('usage', {}).get('input_tokens', 0) for m in self.models)
        out = sum(m.get('usage', {}).get('output_tokens', 0) for m in self.models)
        costs = [m.get('cost', {}).get('usd') for m in self.models]
        sizes = [m['input_chars'] for m in self.models]
        changes = {
            'status': status,
            'finished_at': now(),
            'latency_ms': round(elapsed * 1000),
            'first_token_ms': round(self.first_token * 1000) if self.first_token is not None else None,
            'output_tokens_per_second': round(out / elapsed, 2) if elapsed else None,
            'usage': {
                'input_tokens': inp,
                'output_tokens': out,
                'total_tokens': inp + out,
                'estimated_calls': sum(m.get('usage', {}).get('source') == 'estimated' for m in self.models),
            },
            'cost_usd': round(sum(c for c in costs if c is not None), 9)
            if costs and all(c is not None for c in costs)
            else None,
            'known_cost_usd': round(sum(c for c in costs if c is not None), 9),
            'unpriced_calls': sum(c is None for c in costs),
            'model_call_count': len(self.models),
            'tool_call_count': len(self.tools),
            'skills': [result['skill']] if result.get('skill') else [],
            'response': clean(result.get('content', ''), 32000),
            'sources': [payload(source, 12000) for source in result.get('sources', [])[:60]],
            'error': clean(error, 700),
            'context': {
                **self.doc['context'],
                'prompt_chars': sizes,
                'average_prompt_chars': round(sum(sizes) / len(sizes)) if sizes else 0,
                'model_context': result.get('context_usage'),
                'conversation': result.get('conversation_context') or self.doc['context'].get('conversation'),
            },
            'langfuse': {
                'configured': langfuse_bridge.configured(),
                'trace_id': self.id if self.root else None,
                'export_error': self.lf_error or None,
            },
        }
        try:
            self.persist(**changes)
            if self.root:
                try:
                    self.root.update(
                        output=changes['response'] or changes['error'],
                        metadata={
                            'status': status,
                            'latency_ms': changes['latency_ms'],
                            'model_calls': len(self.models),
                            'tool_calls': len(self.tools),
                        },
                        level='ERROR' if status == 'error' else 'DEFAULT',
                    )
                    self.root.end()
                except Exception:
                    pass
        except Exception:
            import logging

            logging.getLogger(__name__).warning('Could not finalize agent telemetry for %s', self.id)
        finally:
            CURRENT.reset(self.token)


def tool_call(fn):
    @functools.wraps(fn)
    def wrapped(context, name, args):
        trace = CURRENT.get()
        if trace is None:
            return fn(context, name, args)
        started = time.monotonic()
        try:
            result = fn(context, name, args)
        except Exception as exc:
            trace.tool(name, args, {}, time.monotonic() - started, str(exc))
            raise
        error = (
            str(
                result.get('error')
                or (result.get('message') if result.get('not_found') or result.get('ambiguous') else '')
                or ''
            )
            if isinstance(result, dict)
            else ''
        )
        cached = bool(getattr(context, 'trace', []) and context.trace[-1].get('cached'))
        trace.tool(name, args, result, time.monotonic() - started, error, cached)
        return result

    return wrapped
