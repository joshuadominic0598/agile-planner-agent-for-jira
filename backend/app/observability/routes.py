"""Standalone operations dashboard APIs, served separately from the product UI."""

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import store
from ..agent import history_store
from . import langfuse_bridge, pricing

router = APIRouter(prefix='/api/ops', tags=['Agent operations'])


def match(session_id='', dataset_id='', hours=168, kind=''):
    result = {'started_at': {'$gte': (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()}}
    if session_id:
        result['session_id'] = session_id
    if dataset_id:
        result['dataset_id'] = dataset_id
    if kind:
        result['kind'] = kind
    return result


@router.get('/summary')
def summary(
    session_id: str = '',
    dataset_id: str = '',
    hours: int = Query(default=168, ge=1, le=87600),
    kind: str = '',
):
    db = store.mongo()
    query = {**match(session_id, dataset_id, hours, kind), 'status': {'$ne': 'legacy'}}
    pipeline = [
        {'$match': query},
        {
            '$group': {
                '_id': None,
                'requests': {'$sum': 1},
                'success': {'$sum': {'$cond': [{'$eq': ['$status', 'success']}, 1, 0]}},
                'failed': {'$sum': {'$cond': [{'$eq': ['$status', 'error']}, 1, 0]}},
                'running': {'$sum': {'$cond': [{'$eq': ['$status', 'running']}, 1, 0]}},
                'legacy': {'$sum': {'$cond': [{'$eq': ['$status', 'legacy']}, 1, 0]}},
                'avg_latency_ms': {'$avg': '$latency_ms'},
                'avg_first_token_ms': {'$avg': '$first_token_ms'},
                'input_tokens': {'$sum': '$usage.input_tokens'},
                'output_tokens': {'$sum': '$usage.output_tokens'},
                'model_calls': {'$sum': '$model_call_count'},
                'tool_calls': {'$sum': '$tool_call_count'},
                'known_cost_usd': {'$sum': '$known_cost_usd'},
                'unpriced_calls': {'$sum': '$unpriced_calls'},
                'estimated_calls': {'$sum': '$usage.estimated_calls'},
                'avg_prompt_chars': {'$avg': '$context.average_prompt_chars'},
                'chunks_returned': {'$sum': '$context.chunks_returned'},
                'avg_chunk_chars': {'$avg': '$context.average_chunk_chars'},
                'thumbs_up': {'$sum': {'$cond': [{'$eq': ['$feedback.vote', 1]}, 1, 0]}},
                'thumbs_down': {'$sum': {'$cond': [{'$eq': ['$feedback.vote', -1]}, 1, 0]}},
                'avg_output_tokens_per_second': {'$avg': '$output_tokens_per_second'},
            }
        },
    ]
    values = list(db.agent_runs.aggregate(pipeline))
    metrics = {k: v for k, v in (values[0] if values else {'requests': 0}).items() if k != '_id'}
    latencies = sorted(
        r['latency_ms']
        for r in db.agent_runs.find({**query, 'latency_ms': {'$type': 'number'}}, {'latency_ms': 1})
        .sort('started_at', -1)
        .limit(5000)
    )
    metrics['p95_latency_ms'] = latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)] if latencies else None
    metrics['p95_sample_size'] = len(latencies)
    metrics['requests_per_minute'] = metrics.get('requests', 0) / (hours * 60)

    def groups(field):
        return list(
            db.agent_runs.aggregate(
                [
                    {'$match': query},
                    {
                        '$group': {
                            '_id': field,
                            'count': {'$sum': 1},
                            'input_tokens': {'$sum': '$usage.input_tokens'},
                            'output_tokens': {'$sum': '$usage.output_tokens'},
                            'cost_usd': {'$sum': '$known_cost_usd'},
                            'latency_ms': {'$avg': '$latency_ms'},
                        }
                    },
                    {'$sort': {'count': -1}},
                ]
            )
        )

    skills = list(
        db.agent_runs.aggregate(
            [
                {'$match': query},
                {'$unwind': '$skills'},
                {'$group': {'_id': '$skills', 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}},
            ]
        )
    )
    tools = list(
        db.agent_runs.aggregate(
            [
                {'$match': query},
                {'$unwind': '$tool_calls'},
                {
                    '$group': {
                        '_id': '$tool_calls.tool',
                        'count': {'$sum': 1},
                        'latency_ms': {'$avg': '$tool_calls.latency_ms'},
                    }
                },
                {'$sort': {'count': -1}},
            ]
        )
    )
    blocked_query = {'created_at': query['started_at']}
    if session_id:
        blocked_query['session_id'] = session_id
    if dataset_id:
        blocked_query['dataset_id'] = dataset_id
    metrics['blocked_inputs'] = db.agent_guardrails.count_documents(blocked_query)
    return {
        'metrics': metrics,
        'models': groups('$model'),
        'statuses': groups('$status'),
        'timeline': groups({'$substrBytes': ['$started_at', 0, 13]}),
        'skills': skills,
        'tools': tools,
        'langfuse': {
            'configured': langfuse_bridge.configured(),
            'host_configured': langfuse_bridge.configured(),
        },
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'scope': {'session_id': session_id, 'dataset_id': dataset_id, 'hours': hours},
    }


@router.get('/conversations')
def conversations(offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=100)):
    return history_store.list_sessions(None, offset, limit)


@router.get('/runs')
def runs(
    session_id: str = '',
    dataset_id: str = '',
    hours: int = Query(default=168, ge=1, le=87600),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    kind: str = '',
):
    query = match(session_id, dataset_id, hours, kind)
    rows = list(
        store.mongo()
        .agent_runs.find(
            query,
            {
                '_id': 0,
                'model_calls': 0,
                'tool_calls': 0,
                'events': 0,
                'retrieved_contexts': 0,
                'prompt_version': 0,
            },
        )
        .sort('started_at', -1)
        .skip(offset)
        .limit(limit)
    )
    return {'items': rows, 'total': store.mongo().agent_runs.count_documents(query)}


@router.get('/runs/{run_id}')
def run(run_id: str):
    row = store.mongo().agent_runs.find_one({'id': run_id}, {'_id': 0})
    if not row:
        raise HTTPException(404, 'Run not found.')
    return row


@router.get('/conversations/{session_id}/messages')
def conversation_messages(session_id: str, before_id: int | None = None):
    rows = history_store.messages(session_id, before_id, 100)
    return {
        'items': rows,
        'has_more': bool(rows and history_store.has_older(session_id, rows[0]['id'])),
        'before_id': rows[0]['id'] if rows else None,
    }


@router.get('/pricing')
def get_pricing():
    return {
        **pricing.catalog(),
        'overrides': (store.mongo().workspace_settings.find_one({'id': 'pricing'}, {'_id': 0}) or {}).get(
            'rates', {}
        ),
    }


class Rate(BaseModel):
    input: float = Field(ge=0, le=10000)
    output: float = Field(ge=0, le=10000)
    cached_input: float | None = Field(default=None, ge=0, le=10000)


@router.put('/pricing/{provider}/{model}')
def save_price(provider: str, model: str, body: Rate):
    if (
        provider not in {'openai', 'azure', 'gemini', 'compatible'}
        or len(model) > 150
        or '$' in model
        or '.' in model
        and not model.startswith(('gpt-', 'gemini-', 'qwen', 'nemotron'))
    ):
        raise HTTPException(422, 'Use a supported provider and plain model name.')
    row = store.mongo().workspace_settings.find_one({'id': 'pricing'}) or {}
    rates = row.get('rates', {})
    rates[f'{provider}:{model}'] = body.model_dump()
    store.mongo().workspace_settings.update_one({'id': 'pricing'}, {'$set': {'rates': rates}}, upsert=True)
    return {
        'saved': True,
        'note': 'Applies to future calls; previously recorded costs retain their original price snapshot.',
    }
