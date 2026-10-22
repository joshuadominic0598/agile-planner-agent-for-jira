"""Immutable golden-set revisions, with optimistic edits and legacy conversation adoption."""

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, model_validator
from pymongo.errors import DuplicateKeyError

from .. import store
from ..paths import ROOT, data_dir
from .telemetry import now

router = APIRouter(prefix='/api/ops/evaluation', tags=['Evaluation datasets'])


class Expectations(BaseModel):
    clarification: bool = False
    ticket_keys: list[str] = Field(default_factory=list, max_length=100)


class GoldenCase(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=100)
    conversation_id: str = Field(default='conversation-1', min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=3000)
    reference: str = Field(min_length=1, max_length=12000)
    original_reference: str | None = Field(default=None, max_length=12000)
    reference_status: Literal['verified', 'needs_human_verification', 'curated_behavior'] = (
        'needs_human_verification'
    )
    reference_contexts: list[Annotated[str, Field(max_length=6000)]] = Field(
        default_factory=list, max_length=12
    )
    context_status: Literal['verified', 'needs_human_verification', 'missing'] = 'missing'
    context_source: str = Field(default='', max_length=500)
    reference_context_ids: list[Annotated[str, Field(max_length=100)]] = Field(
        default_factory=list, max_length=100
    )
    provided_context_ids: list[Annotated[str, Field(max_length=100)]] = Field(
        default_factory=list, max_length=100
    )
    provided_answer: str | None = Field(default=None, max_length=32000)
    provided_contexts: list[Annotated[str, Field(max_length=6000)]] = Field(
        default_factory=list, max_length=24
    )
    enabled: bool = True
    expected: Expectations = Field(default_factory=Expectations)

    @model_validator(mode='after')
    def context_state(self):
        self.reference_contexts = [text for text in self.reference_contexts if text.strip()]
        if not self.reference_contexts:
            self.context_status = 'missing'
        elif self.context_status == 'missing':
            self.context_status = 'needs_human_verification'
        return self


class DatasetWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default='', max_length=2000)
    ticket_dataset_id: str = Field(default='', max_length=100)
    cases: list[GoldenCase] = Field(min_length=1, max_length=200)
    base_version_id: str = Field(default='', max_length=100)
    change_note: str = Field(default='', max_length=500)


def setup():
    db = store.mongo()
    for collection in ['agent_eval_datasets', 'agent_eval_versions', 'agent_eval_jobs']:
        db[collection].create_index('id', unique=True)
    db.agent_eval_versions.create_index([('dataset_id', 1), ('created_at', -1)])


def dataset(ident):
    row = store.mongo().agent_eval_datasets.find_one({'id': ident}, {'_id': 0})
    if not row:
        raise HTTPException(404, 'Evaluation dataset not found.')
    return row


def version(ident):
    row = store.mongo().agent_eval_versions.find_one({'id': ident}, {'_id': 0})
    if not row:
        raise HTTPException(404, 'Dataset version not found.')
    return row


def publish(ident, body, source=None):
    db = store.mongo()
    current = dataset(ident)
    if current.get('head_version_id', '') != body.base_version_id:
        raise HTTPException(409, 'This dataset changed. Reload its latest version before saving your edits.')
    if not body.name.strip() or any(not c.question.strip() or not c.reference.strip() for c in body.cases):
        raise HTTPException(422, 'Give the dataset, each question and each expected answer readable text.')
    if len({c.id for c in body.cases}) != len(body.cases):
        raise HTTPException(422, 'Each exchange must have a distinct ID.')
    target = store.dataset(body.ticket_dataset_id) if body.ticket_dataset_id else None
    if body.ticket_dataset_id and (not target or target['status'] != 'ready'):
        raise HTTPException(422, 'Choose a ready ticket export.')
    parent = version(body.base_version_id) if body.base_version_id else None
    originals = {c['id']: c for c in parent['cases']} if parent else {}
    cases = []
    for i, c in enumerate(body.cases):
        value = c.model_dump()
        old = originals.get(c.id, {})
        value.update(
            case_number=i + 1,
            original_reference=old.get('original_reference') or c.original_reference or c.reference,
        )
        if (
            parent
            and target
            and parent.get('source_snapshot_sha256') != target.get('metadata', {}).get('sha256')
        ):
            if value['reference_status'] != 'curated_behavior':
                value['reference_status'] = 'needs_human_verification'
        cases.append(value)
    encoded = json.dumps(cases, sort_keys=True, ensure_ascii=False).encode()
    if len(encoded) > 6_000_000:
        raise HTTPException(
            422, 'Dataset evidence is too large. Split it into smaller datasets (up to 6 MB per version).'
        )
    sha = hashlib.sha256(encoded).hexdigest()
    row = {
        'id': uuid.uuid4().hex,
        'dataset_id': ident,
        'number': parent['number'] + 1 if parent else 1,
        'parent_id': body.base_version_id or None,
        'created_at': now(),
        'name': body.name.strip(),
        'notes': body.notes,
        'change_note': body.change_note,
        'ticket_dataset_id': body.ticket_dataset_id,
        'source_snapshot_sha256': (target or {}).get('metadata', {}).get('sha256')
        or current.get('source_snapshot_sha256'),
        'source': source or (parent or {}).get('source') or current.get('source', {}),
        'sha256': sha,
        'cases': cases,
        'case_count': len(cases),
        'enabled_count': sum(c['enabled'] for c in cases),
    }
    db.agent_eval_versions.insert_one(row.copy())
    update = db.agent_eval_datasets.update_one(
        {'id': ident, 'head_version_id': body.base_version_id},
        {'$set': {'head_version_id': row['id'], 'name': row['name'], 'updated_at': now()}},
    )
    if not update.modified_count:
        db.agent_eval_versions.delete_one({'id': row['id']})
        raise HTTPException(409, 'Another edit was saved first. Reload before publishing a new version.')
    return row


def create(body, ident=None, source=None, kind='custom', snapshot=None):
    setup()
    ident = ident or uuid.uuid4().hex
    row = {
        'id': ident,
        'name': body.name,
        'head_version_id': '',
        'created_at': now(),
        'updated_at': now(),
        'kind': kind,
        'source': source or {},
        'source_snapshot_sha256': snapshot,
    }
    try:
        store.mongo().agent_eval_datasets.insert_one(row.copy())
    except DuplicateKeyError:
        for _ in range(20):
            head = dataset(ident)['head_version_id']
            if head:
                return version(head)
            time.sleep(0.05)
        raise HTTPException(409, 'Dataset is being initialized; refresh in a moment.')
    try:
        return publish(ident, body, source)
    except Exception:
        store.mongo().agent_eval_datasets.delete_one({'id': ident, 'head_version_id': ''})
        raise


def adopt_legacy():
    db = store.mongo()
    setup()
    for digest in db.agent_eval_cases.distinct('dataset_version'):
        ident = 'conversation-' + digest[:24]
        if db.agent_eval_datasets.find_one({'id': ident}):
            continue
        rows = list(db.agent_eval_cases.find({'dataset_version': digest}, {'_id': 0}).sort('case_number', 1))
        if not rows:
            continue
        latest = db.agent_evaluations.find_one({'dataset_version': digest}, sort=[('started_at', -1)]) or {}
        target = latest.get('dataset_id', '')
        if target and not store.dataset(target):
            target = ''
        for case in rows:
            previous, evidence = {}, []
            candidates = (
                db.agent_eval_results.find(
                    {
                        'case_id': case['id'],
                        '$or': [
                            {'retrieved_contexts': {'$type': 'array', '$ne': []}},
                            {'run_id': {'$type': 'string'}},
                        ],
                    }
                )
                .sort('started_at', 1)
                .limit(30)
            )
            for candidate in candidates:
                trace = db.agent_runs.find_one({'id': candidate.get('run_id')}) or {}
                found = candidate.get('retrieved_contexts') or trace.get('retrieved_contexts') or []
                if found:
                    previous, evidence = candidate, found
                    break
            case.update(
                reference_contexts=[str(t)[:6000] for t in evidence[:12]],
                context_status='needs_human_verification' if evidence else 'missing',
                context_source=(
                    'Candidate evidence from historical run '
                    + str(previous.get('run_id'))
                    + '; first 12 chunks, not independently verified.'
                )
                if evidence
                else 'No captured context was available in the imported conversation or saved trace.',
            )
        body = DatasetWrite(
            name=rows[0].get('source', {}).get('file', 'Imported conversation'),
            notes='Imported conversation. Earlier edits were not versioned; original answers remain available in historical results.',
            ticket_dataset_id=target,
            cases=[GoldenCase(**r) for r in rows],
            change_note='Adopt existing conversation into version history',
        )
        create(body, ident, rows[0].get('source'), kind='conversation')
        # Legacy runs keep their original frozen references; do not pretend they used a new revision.
        db.agent_evaluations.update_many(
            {'dataset_version': digest},
            {'$set': {'golden_dataset_id': ident, 'legacy_dataset_version': True}},
        )
        db.agent_eval_datasets.update_one({'id': ident}, {'$set': {'legacy_document_sha256': digest}})


def ensure_demo():
    path = ROOT / 'resources/demo/agileplanner-evaluation.json'
    if not path.is_file():
        return
    value = json.loads(path.read_text())
    if store.mongo().agent_eval_datasets.find_one({'id': 'agileplanner-demo-golden'}):
        return
    body = DatasetWrite(
        name=value['name'],
        notes=value['notes'],
        cases=value['cases'],
        change_note='Built-in benchmark verified against the fictional CSV',
    )
    create(
        body,
        'agileplanner-demo-golden',
        {'file': path.name, 'kind': 'bundled_csv_facts'},
        kind='demo',
        snapshot=value['source_snapshot_sha256'],
    )


def replay_cases(v):
    return [
        {**c, 'dataset_version': v['sha256'], 'source': {'file': v['name'] + ' · v' + str(v['number'])}}
        for c in v['cases']
        if c.get('enabled', True)
    ]


@router.get('/datasets')
def catalog():
    adopt_legacy()
    ensure_demo()
    db = store.mongo()
    values = []
    for row in db.agent_eval_datasets.find({}, {'_id': 0}).sort('updated_at', -1):
        head = version(row['head_version_id'])
        values.append(
            {
                **row,
                'version_number': head['number'],
                'case_count': head['case_count'],
                'enabled_count': head['enabled_count'],
                'ticket_dataset_id': head['ticket_dataset_id'],
                'source_snapshot_sha256': head.get('source_snapshot_sha256'),
            }
        )
    exports = [
        {'id': d['id'], 'filename': d['filename'], 'sha256': d.get('metadata', {}).get('sha256')}
        for d in db.datasets.find({'status': 'ready'}, {'_id': 0}).sort('imported_at', -1)
    ]
    active = (db.workspace_settings.find_one({'id': 'workspace'}) or {}).get('active_dataset', '')
    from ..agent import connections

    return {
        'datasets': values,
        'exports': exports,
        'active_export_id': active,
        'connections': connections.choices(),
    }


@router.post('/datasets', status_code=201)
def new_dataset(body: DatasetWrite):
    if body.base_version_id:
        raise HTTPException(422, 'A new dataset starts with version 1.')
    return create(body)


@router.get('/datasets/{ident}/versions')
def versions(ident: str):
    head = dataset(ident)['head_version_id']
    history = []
    while head and len(history) < 1000:
        v = version(head)
        history.append({k: value for k, value in v.items() if k != 'cases'})
        head = v['parent_id']
    return history


@router.get('/datasets/{ident}/versions/{version_id}')
def read_version(ident: str, version_id: str):
    v = version(version_id)
    if v['dataset_id'] != ident:
        raise HTTPException(404, 'Version does not belong to this dataset.')
    return v


@router.post('/datasets/{ident}/versions', status_code=201)
def save_version(ident: str, body: DatasetWrite):
    return publish(ident, body)


@router.post('/import', status_code=201)
async def upload_document(file: UploadFile = File(), ticket_dataset_id: str = Form(default='')):
    content = await file.read(3_000_001)
    await file.close()
    if len(content) > 3_000_000:
        raise HTTPException(413, 'Choose a conversation file up to 3 MB.')
    name = Path((file.filename or '').replace('\\', '/')).name
    try:
        if name.lower().endswith('.csv'):
            from .evaluation_import import parse_csv

            body = DatasetWrite(name=name, ticket_dataset_id=ticket_dataset_id, cases=parse_csv(content))
        elif name.lower().endswith('.json'):
            value = json.loads(content)
            from .evaluation_import import convert

            if isinstance(value, list):
                value = {'name': name, 'cases': value}
            body = DatasetWrite(
                name=value.get('name', name),
                notes=value.get('notes', ''),
                ticket_dataset_id=ticket_dataset_id,
                cases=[convert(row) for row in value['cases']],
            )
        elif name.lower().endswith('.docx'):
            from io import BytesIO
            from zipfile import ZipFile

            with ZipFile(BytesIO(content)) as z:
                if sum(i.file_size for i in z.infolist()) > 12_000_000:
                    raise ValueError('The expanded document is too large.')
            folder = data_dir() / 'uploads/evaluation'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (uuid.uuid4().hex + '.docx')
            path.touch(mode=0o600)
            path.write_bytes(content)
            from .evaluation import import_document

            rows = import_document(path, persist=False)
            body = DatasetWrite(
                name=name, ticket_dataset_id=ticket_dataset_id, cases=[GoldenCase(**r) for r in rows]
            )
        else:
            raise ValueError('Choose a UTF-8 .csv, .docx conversation or exported .json evaluation dataset.')
        return create(body, source={'file': name, 'sha256': hashlib.sha256(content).hexdigest()})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, 'Could not import this conversation: ' + str(exc)[:300]) from exc


@router.get('/datasets/{ident}/performance')
def performance(ident: str, version_id: str = ''):
    dataset(ident)
    db = store.mongo()
    runs = list(
        db.agent_evaluations.find(
            {'golden_dataset_id': ident, **({'golden_version_id': version_id} if version_id else {})},
            {'_id': 0, 'case_snapshot': 0, 'prompt_snapshot': 0},
        )
        .sort('started_at', -1)
        .limit(100)
    )
    summaries = {
        r['_id']: r
        for r in db.agent_eval_results.aggregate(
            [
                {'$match': {'evaluation_id': {'$in': [r['id'] for r in runs]}}},
                {
                    '$group': {
                        '_id': '$evaluation_id',
                        'faithfulness': {'$avg': '$ragas.metrics.faithfulness'},
                        'context_precision': {'$avg': '$ragas.metrics.context_precision'},
                        'human_score': {'$avg': '$human.score'},
                        'bleu4': {'$avg': '$metrics.ngrams.bleu.4'},
                        'rouge_l': {'$avg': '$metrics.ngrams.rouge_l.f1'},
                        'latency_ms': {'$avg': '$generation_latency_ms'},
                    }
                },
            ]
        )
    }
    return [
        {**r, 'summary': {k: value for k, value in summaries.get(r['id'], {}).items() if k != '_id'}}
        for r in runs
    ]


@router.get('/template.csv')
def csv_template():
    from fastapi.responses import FileResponse

    return FileResponse(
        ROOT / 'resources/demo/evaluation-template.csv',
        media_type='text/csv',
        filename='evaluation-template.csv',
    )
