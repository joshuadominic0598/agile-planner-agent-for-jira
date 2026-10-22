"""Feedback for successful and failed responses, linked to the durable run ID."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import store
from . import langfuse_bridge
from .telemetry import clean, now

router = APIRouter(prefix='/api/agent/runs', tags=['Agent feedback'])


class Feedback(BaseModel):
    vote: Literal[-1, 0, 1] | None = None
    note: str | None = Field(default=None, max_length=300)


@router.post('/{run_id}/feedback')
def feedback(run_id: str, body: Feedback):
    db = store.mongo()
    run = db.agent_runs.find_one({'id': run_id}, {'_id': 0})
    if not run:
        raise HTTPException(404, 'This response was not found.')
    previous = run.get('feedback') or {}
    value = {**previous, 'updated_at': now()}
    if body.vote is not None:
        value['vote'] = body.vote
    if body.note is not None:
        value['note'] = clean(body.note.strip(), 300)
    db.agent_runs.update_one({'id': run_id}, {'$set': {'feedback': value}})
    db.agent_messages.update_many({'payload.run_id': run_id}, {'$set': {'payload.feedback': value}})
    try:
        if body.vote is not None:
            langfuse_bridge.score(run_id, 'user_feedback', body.vote, value.get('note', ''))
        elif value.get('note'):
            langfuse_bridge.score(run_id, 'feedback_note', 0, value['note'])
    except Exception:
        db.agent_runs.update_one({'id': run_id}, {'$set': {'langfuse.feedback_pending': True}})
    return {'saved': True, 'feedback': value}
