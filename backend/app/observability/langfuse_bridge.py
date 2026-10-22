"""Optional native Langfuse observations; local tracing never depends on its availability."""

import os
from functools import lru_cache


def configured():
    return bool(os.getenv('LANGFUSE_PUBLIC_KEY') and os.getenv('LANGFUSE_SECRET_KEY'))


@lru_cache(maxsize=1)
def client():
    if not configured():
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=os.environ['LANGFUSE_PUBLIC_KEY'],
        secret_key=os.environ['LANGFUSE_SECRET_KEY'],
        base_url=os.getenv('LANGFUSE_BASE_URL', 'https://cloud.langfuse.com'),
        timeout=5,
    )


def start(trace_id, session_id, name, kind, input, parent=None, model=None):
    sdk = client()
    if sdk is None:
        return None
    from langfuse import propagate_attributes

    with propagate_attributes(session_id=session_id, tags=['agileplanner']):
        return sdk.start_observation(
            name=name,
            as_type=kind,
            trace_context={'trace_id': trace_id, **({'parent_span_id': parent} if parent else {})},
            input=input,
            **({'model': model} if model else {}),
        )


def score(trace_id, name, value, note=''):
    sdk = client()
    if sdk:
        from .telemetry import clean

        sdk.create_score(
            trace_id=trace_id, name=name, value=value, comment=clean(note, 1000), data_type='NUMERIC'
        )


def evaluation_scores(trace_id, result):
    if not trace_id or not configured():
        return
    for name, value in result.get('metrics', {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                score(trace_id, 'ragas_' + name, value, 'Automated evidence score; human review pending.')
            except Exception:
                pass
