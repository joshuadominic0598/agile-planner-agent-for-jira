"""Durable evaluation jobs launched from the dashboard; model secrets stay in MongoDB."""

import argparse
import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import store
from ..agent import connections, prompt_versions
from ..paths import ROOT
from . import evaluation_datasets as golden
from .telemetry import clean, now

router = APIRouter(prefix='/api/ops/evaluation', tags=['Evaluation execution'])


class Launch(BaseModel):
    golden_dataset_id: str
    version_id: str
    prompt_version_id: str = Field(default='', max_length=100)
    ticket_dataset_id: str = ''
    run_mode: Literal['agent', 'provided'] = 'agent'
    connection_ids: list[str] = Field(min_length=1, max_length=2)
    judge_connection_id: str = ''
    effort: Literal['low', 'standard', 'high'] = 'standard'
    ragas: bool = True
    delay: float = Field(default=3, ge=0, le=60)


def application_base():
    return os.getenv('JIRA_EVAL_APP_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')


def launch(body, spawn=True):
    golden.setup()
    golden.dataset(body.golden_dataset_id)
    v = golden.version(body.version_id)
    if v['dataset_id'] != body.golden_dataset_id:
        raise HTTPException(422, 'Select a version from this evaluation dataset.')
    if not golden.replay_cases(v):
        raise HTTPException(422, 'Enable at least one exchange before testing.')
    source = store.dataset(body.ticket_dataset_id)
    if body.run_mode == 'agent' and (not source or source['status'] != 'ready'):
        raise HTTPException(422, 'Select a ready ticket export to evaluate against.')
    if (
        body.run_mode == 'agent'
        and v.get('source_snapshot_sha256')
        and v['source_snapshot_sha256'] != (source or {}).get('metadata', {}).get('sha256')
    ):
        raise HTTPException(
            422,
            'This golden version belongs to a different ticket export. Rebind and save a new version before testing.',
        )
    if body.run_mode == 'provided' and len(body.connection_ids) != 1:
        raise HTTPException(
            422,
            'Uploaded responses are one fixed output set. Compare generating models with agent evaluation instead.',
        )
    if (
        body.run_mode == 'provided'
        and not body.ragas
        and not any(c.get('provided_answer') for c in v['cases'])
    ):
        raise HTTPException(
            422,
            'Enable Ragas to check expected answers against evidence, or provide both reference_answer and answer for overlap scoring.',
        )
    if len(set(body.connection_ids)) != len(body.connection_ids):
        raise HTTPException(422, 'Choose two different connections for a comparison.')
    for ident in body.connection_ids + ([body.judge_connection_id] if body.judge_connection_id else []):
        try:
            cfg = connections.resolve(ident)
            if cfg.get('provider') == 'disabled':
                raise ValueError('No model configured.')
        except Exception as exc:
            raise HTTPException(422, 'Choose a configured model connection.') from exc
    if body.ragas and not body.judge_connection_id:
        raise HTTPException(422, 'Choose one common judge model for Ragas scoring.')
    if body.run_mode == 'agent':
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(
                    application_base() + f'/api/datasets/{body.ticket_dataset_id}/agent/status'
                )
                response.raise_for_status()
                if response.json().get('status') != 'ready':
                    raise HTTPException(
                        409, 'The agent index is not ready. Prepare it in Sprint Agent → Configure first.'
                    )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                503, 'The main application is unavailable. Start it with make start.'
            ) from exc
    python = ROOT / '.venv-evaluation/bin/python' if body.ragas else Path(sys.executable)
    if body.ragas and not python.is_file():
        raise HTTPException(422, 'Run make evaluation-setup once to install the Ragas evaluation tools.')
    ident = uuid.uuid4().hex
    prompt = (
        prompt_versions.get(body.ticket_dataset_id, body.prompt_version_id)
        if body.run_mode == 'agent'
        else None
    )
    run_ids = [uuid.uuid4().hex for _ in body.connection_ids]
    job = {
        'id': ident,
        **body.model_dump(),
        'prompt_version_id': prompt['id'] if prompt else None,
        'prompt_version_number': prompt['number'] if prompt else None,
        'run_ids': run_ids,
        'status': 'queued',
        'created_at': now(),
        'updated_at': now(),
        'version_number': v['number'],
        'case_count': v['enabled_count'],
        'completed_models': 0,
    }
    store.mongo().agent_eval_jobs.insert_one(job.copy())
    if spawn:
        folder = ROOT / 'resources/evaluation/jobs'
        folder.mkdir(parents=True, exist_ok=True)
        log_path = folder / (ident + '.log')
        log_path.touch(mode=0o600)
        try:
            with log_path.open('a') as log:
                process = subprocess.Popen(
                    [str(python), '-m', 'app.observability.evaluation_jobs', '--job', ident],
                    cwd=ROOT,
                    env={**os.environ, 'PYTHONPATH': str(ROOT / 'backend')},
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            store.mongo().agent_eval_jobs.update_one({'id': ident}, {'$set': {'pid': process.pid}})
        except Exception as exc:
            store.mongo().agent_eval_jobs.update_one(
                {'id': ident}, {'$set': {'status': 'error', 'error': clean(str(exc), 400)}}
            )
            raise HTTPException(503, 'Could not start the evaluation worker.') from exc
    return job


@router.post('/jobs', status_code=202)
def start_job(body: Launch):
    return launch(body)


@router.get('/jobs')
def jobs():
    return list(store.mongo().agent_eval_jobs.find({}, {'_id': 0}).sort('created_at', -1).limit(30))


@router.get('/jobs/{ident}')
def job_status(ident: str):
    job = store.mongo().agent_eval_jobs.find_one({'id': ident}, {'_id': 0})
    if not job:
        raise HTTPException(404, 'Evaluation job not found.')
    progress = list(
        store.mongo().agent_evaluations.find(
            {'id': {'$in': job['run_ids']}},
            {'_id': 0, 'id': 1, 'model': 1, 'status': 1, 'completed': 1, 'failed': 1, 'case_count': 1},
        )
    )
    if job['status'] in {'queued', 'running'} and job.get('pid'):
        try:
            os.kill(job['pid'], 0)
        except ProcessLookupError:
            job.update(
                status='interrupted',
                error='The worker stopped. Completed results are preserved; start a new test to retry.',
            )
            store.mongo().agent_eval_jobs.update_one(
                {'id': ident}, {'$set': {'status': job['status'], 'error': job['error']}}
            )
    progress.sort(key=lambda row: job['run_ids'].index(row['id']))
    return {**job, 'runs': progress}


@router.post('/jobs/{ident}/cancel')
def cancel(ident: str):
    job = job_status(ident)
    if job['status'] in {'queued', 'running'} and job.get('pid'):
        store.mongo().agent_eval_jobs.update_one({'id': ident}, {'$set': {'cancel_requested': True}})
        try:
            os.kill(job['pid'], signal.SIGTERM)
        except ProcessLookupError:
            pass
    return {'saved': True}


class Cancelled(BaseException):
    pass


def execute(ident):
    db = store.mongo()
    job = db.agent_eval_jobs.find_one({'id': ident})
    if not job:
        raise ValueError('Job not found.')
    v = golden.version(job['version_id'])
    cases = golden.replay_cases(v)
    from .evaluation import replay

    db.agent_eval_jobs.update_one({'id': ident}, {'$set': {'status': 'running', 'updated_at': now()}})
    status, error = 'complete', ''
    try:
        for pos, connection in enumerate(job['connection_ids']):
            if job.get('run_mode') == 'provided':
                from .provided_evaluation import score

                score(job, v, job['run_ids'][pos])
                db.agent_eval_jobs.update_one({'id': ident}, {'$set': {'completed_models': pos + 1}})
                continue
            replay(
                application_base(),
                job['ticket_dataset_id'],
                connection,
                cases,
                job['effort'],
                job['ragas'],
                job['delay'],
                job['run_ids'][pos],
                job.get('judge_connection_id') or None,
                golden_version=v,
                job_id=ident,
                prompt_version_id=job.get('prompt_version_id') or '',
            )
            db.agent_eval_jobs.update_one(
                {'id': ident}, {'$set': {'completed_models': pos + 1, 'updated_at': now()}}
            )
    except Cancelled:
        status = 'cancelled'
    except Exception as exc:
        status, error = 'error', clean(str(exc), 700)
    finally:
        db.agent_eval_jobs.update_one(
            {'id': ident}, {'$set': {'status': status, 'error': error, 'finished_at': now()}}
        )
        db.agent_evaluations.update_many(
            {'id': {'$in': job['run_ids']}, 'status': 'running'},
            {'$set': {'status': status if status != 'complete' else 'error', 'finished_at': now()}},
        )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    args = parser.parse_args()

    def stop(*_args):
        raise Cancelled()

    signal.signal(signal.SIGTERM, stop)
    execute(args.job)
