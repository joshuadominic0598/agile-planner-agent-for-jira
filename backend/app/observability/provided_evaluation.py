"""Score uploaded responses without presenting them as newly generated model answers."""

import asyncio
import uuid

from .. import store
from ..agent import connections
from . import evaluation_datasets as golden
from .evaluation import deterministic_metrics, pipeline_version, ragas_scores
from .telemetry import clean, now


def score(job, v, ident):
    db = store.mongo()
    cfg = connections.resolve(job.get('judge_connection_id') or job['connection_ids'][0])
    cases = golden.replay_cases(v)
    db.agent_evaluations.insert_one(
        {
            'id': ident,
            'dataset_id': job.get('ticket_dataset_id', ''),
            'golden_dataset_id': v['dataset_id'],
            'golden_version_id': v['id'],
            'golden_version_number': v['number'],
            'golden_name': v['name'],
            'dataset_version': v['sha256'],
            'case_snapshot': cases,
            'job_id': job['id'],
            'model': 'Uploaded answers',
            'judge_model': cfg['model'],
            'provider': 'imported',
            'kind': 'provided_outputs',
            'status': 'running',
            'started_at': now(),
            'completed': 0,
            'failed': 0,
            'case_count': len(cases),
            'source_file': v['name'],
            'pipeline_version': pipeline_version(),
            'ragas_enabled': job['ragas'],
            'effort': 'provided_outputs',
        }
    )
    completed, failed = 0, 0
    for case in cases:
        candidate = case.get('provided_answer')
        answer = candidate or case['reference']
        actual_contexts = case.get('provided_contexts') or []
        evidence = actual_contexts or case.get('reference_contexts') or []
        row = {
            'id': uuid.uuid4().hex,
            'evaluation_id': ident,
            'case_id': case['id'],
            'case_number': case['case_number'],
            'question': case['question'],
            'reference': case['reference'],
            'reference_status': case['reference_status'],
            'reference_contexts': case['reference_contexts'],
            'context_status': case['context_status'],
            'context_source': case['context_source'],
            'retrieved_contexts': actual_contexts,
            'reference_validation_contexts': evidence if not actual_contexts else [],
            'response': answer,
            'model': 'Uploaded answers',
            'golden_dataset_id': v['dataset_id'],
            'golden_version_id': v['id'],
            'started_at': now(),
            'sources': [],
            'generation_instrumentation': 'not_provided',
            'reference_validation': not bool(candidate),
        }
        try:
            metrics = (
                deterministic_metrics(case, answer, [])
                if candidate
                else {
                    'reference_verified': case['reference_status'] == 'verified',
                    'overlap_not_applicable': 'The expected answer itself is being checked against evidence; self-overlap is not an evaluation score.',
                }
            )
            ragas = (
                asyncio.run(
                    ragas_scores(
                        case['question'],
                        answer,
                        evidence,
                        cfg,
                        case['reference'],
                        'semantic' if actual_contexts else 'reference_validation',
                        job.get('ticket_dataset_id') or 'golden:' + v['dataset_id'],
                        job['id'],
                        case.get('reference_contexts', []),
                        case['reference_status'] == 'verified',
                        case['context_status'] == 'verified',
                    )
                )
                if job['ragas']
                else {'status': 'not_run', 'reason': 'Ragas disabled.'}
            )
            row.update(status='success', metrics=metrics, ragas=ragas)
            completed += 1
        except Exception as exc:
            row.update(status='error', error=clean(str(exc), 700), metrics={}, ragas={'status': 'error'})
            failed += 1
        row['finished_at'] = now()
        db.agent_eval_results.insert_one(row)
        db.agent_evaluations.update_one(
            {'id': ident}, {'$set': {'completed': completed, 'failed': failed, 'updated_at': now()}}
        )
    db.agent_evaluations.update_one({'id': ident}, {'$set': {'status': 'complete', 'finished_at': now()}})
