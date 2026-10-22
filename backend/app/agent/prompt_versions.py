"""Immutable project guidance bundles; evaluations pin revisions without changing chat settings."""

import hashlib
import json
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .. import store
from ..observability.telemetry import now


class Brief(BaseModel):
    project: str = Field(default='', max_length=100)
    content: str = Field(default='', max_length=12000)


class PromptWrite(BaseModel):
    base_version_id: str = Field(max_length=100)
    briefs: list[Brief] = Field(max_length=100)
    change_note: str = Field(default='', max_length=500)


def setup():
    db = store.mongo()
    db.agent_prompt_heads.create_index('dataset_id', unique=True)
    db.agent_prompt_versions.create_index('id', unique=True)
    db.agent_prompt_versions.create_index([('dataset_id', 1), ('number', -1)])


def make_version(dataset_id, briefs, number, parent=None, note=''):
    normalized = sorted(
        [{'project': b['project'], 'content': b['content'].strip()} for b in briefs],
        key=lambda b: b['project'],
    )
    if len({b['project'] for b in normalized}) != len(normalized):
        raise HTTPException(422, 'Use one brief per project and one shared brief.')
    for b in normalized:
        if b['project'] and not store.summaries(dataset_id, b['project']):
            raise HTTPException(422, 'A project brief must belong to this ticket export.')
    return {
        'id': uuid.uuid4().hex,
        'dataset_id': dataset_id,
        'number': number,
        'parent_id': parent,
        'briefs': normalized,
        'sha256': hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest(),
        'created_at': now(),
        'change_note': note,
    }


def head(dataset_id):
    if not store.dataset(dataset_id):
        raise HTTPException(404, 'Ticket export not found.')
    setup()
    db = store.mongo()
    row = db.agent_prompt_heads.find_one({'dataset_id': dataset_id}, {'_id': 0})
    if row:
        return row
    briefs = list(db.agent_project_context.find({'dataset_id': dataset_id}, {'_id': 0}))
    v = make_version(dataset_id, briefs, 1, note='Capture existing project guidance')
    v['id'] = uuid.uuid5(uuid.NAMESPACE_URL, 'agileplanner:prompt:' + dataset_id).hex
    db.agent_prompt_versions.update_one({'id': v['id']}, {'$setOnInsert': v}, upsert=True)
    db.agent_prompt_heads.update_one(
        {'dataset_id': dataset_id},
        {
            '$setOnInsert': {
                'dataset_id': dataset_id,
                'head_version_id': v['id'],
                'active_version_id': v['id'],
            }
        },
        upsert=True,
    )
    return db.agent_prompt_heads.find_one({'dataset_id': dataset_id}, {'_id': 0})


def get(dataset_id, ident=''):
    if not ident:
        ident = head(dataset_id)['active_version_id']
    v = store.mongo().agent_prompt_versions.find_one({'id': ident, 'dataset_id': dataset_id}, {'_id': 0})
    if not v:
        raise HTTPException(404, 'Prompt version not found in this ticket export.')
    return v


def catalog(dataset_id):
    current = head(dataset_id)
    versions = list(
        store.mongo().agent_prompt_versions.find({'dataset_id': dataset_id}, {'_id': 0}).sort('number', -1)
    )
    projects = sorted({r['project_key'] for r in store.summaries(dataset_id) if r.get('project_key')})
    return {**current, 'versions': versions, 'projects': projects}


def save(dataset_id, body, activate=False):
    current = head(dataset_id)
    if current['head_version_id'] != body.base_version_id:
        raise HTTPException(409, 'Project prompts changed. Reload the latest revision before saving.')
    parent = get(dataset_id, body.base_version_id)
    v = make_version(
        dataset_id,
        [b.model_dump() for b in body.briefs],
        parent['number'] + 1,
        parent['id'],
        body.change_note,
    )
    db = store.mongo()
    db.agent_prompt_versions.insert_one(v.copy())
    fields = {'head_version_id': v['id']}
    if activate:
        fields['active_version_id'] = v['id']
    result = db.agent_prompt_heads.update_one(
        {'dataset_id': dataset_id, 'head_version_id': parent['id']}, {'$set': fields}
    )
    if not result.modified_count:
        db.agent_prompt_versions.delete_one({'id': v['id']})
        raise HTTPException(409, 'Another prompt edit was saved first. Reload before saving.')
    return v


def activate(dataset_id, ident):
    v = get(dataset_id, ident)
    store.mongo().agent_prompt_heads.update_one(
        {'dataset_id': dataset_id}, {'$set': {'active_version_id': ident}}
    )
    return v
