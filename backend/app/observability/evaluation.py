"""Versioned conversation replay, transparent metrics and human-verified references."""

import argparse
import asyncio
import hashlib
import json
import math
import re
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import store
from ..agent import connections
from . import langfuse_bridge, reference_metrics, telemetry
from .telemetry import clean, now

router = APIRouter(prefix='/api/ops/evaluation', tags=['Agent evaluation'])


def import_document(path, persist=True):
    source = Path(path).expanduser().resolve()
    paragraphs = []
    with ZipFile(source) as archive:
        for name in archive.namelist():
            if re.fullmatch(r'word/document\w*\.xml', name):
                root = ElementTree.fromstring(archive.read(name))
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                paragraphs.extend(
                    ''.join(t.text or '' for t in p.findall('.//w:t', ns)).strip()
                    for p in root.findall('.//w:p', ns)
                )
    lines = [line for line in paragraphs if line]
    starts = [i - 1 for i, line in enumerate(lines) if line.startswith('Sprint Agent ·') and i > 0]
    version = hashlib.sha256(source.read_bytes()).hexdigest()
    cases = []
    history = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        question = lines[start]
        answer = []
        for line in lines[start + 2 : end]:
            if line == 'You' or re.match(
                r'^(Actions ·|View steps|Conversation scope:|All projects ·|[A-Z][A-Z0-9_-]* ·|Answer start|Latest|ContextConversation|Read-only|Remembering:|Tools used|Ticket sources|Sprint Agent$)',
                line,
            ):
                continue
            if re.fullmatch(r'\d+\.', line) or re.fullmatch(r'\w+ analysis', line):
                continue
            answer.append(line)
        reference = '\n'.join(answer).strip()
        ambiguous = question.casefold() in {
            'explain this ticket',
            'sorry that was the wrong ticket you found',
        }
        ident = 'doc-' + hashlib.sha256((version + str(n)).encode()).hexdigest()[:18]
        case = {
            'id': ident,
            'dataset_version': version,
            'case_number': n + 1,
            'question': question,
            'original_reference': reference,
            'reference': (
                'Ask a focused question to identify the intended ticket; do not choose an unrelated issue.'
                if ambiguous
                else reference
            ),
            'reference_status': 'curated_behavior' if ambiguous else 'needs_human_verification',
            'source': {'file': source.name, 'sha256': version, 'paragraph_start': start + 1},
            'history': history[-10:],
            'expected': {
                'clarification': ambiguous,
                'ticket_keys': list(dict.fromkeys(re.findall(r'\b[A-Z][A-Z0-9_]+-\d+\b', question, re.I))),
            },
            'created_at': now(),
        }
        if persist:
            store.mongo().agent_eval_cases.update_one({'id': ident}, {'$setOnInsert': case}, upsert=True)
            case = store.mongo().agent_eval_cases.find_one({'id': ident}, {'_id': 0})
        cases.append(case)
        history += [{'role': 'user', 'content': question}, {'role': 'assistant', 'content': reference}]
    if not cases:
        raise ValueError('No question/agent pairs were found in the conversation document.')
    return cases


def deterministic_metrics(case, response, sources):
    a = set(re.findall(r'\w+', response.casefold()))
    b = set(re.findall(r'\w+', case['reference'].casefold()))
    precision = len(a & b) / len(a) if a else 0
    recall = len(a & b) / len(b) if b else 0
    expected = set(k.upper() for k in case['expected']['ticket_keys'])
    cited = {s['key'].upper() for s in sources}
    found = expected & (cited | set(re.findall(r'\b[A-Z][A-Z0-9_]+-\d+\b', response)))
    return {
        'reference_token_f1': round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0,
        'ticket_reference_recall': len(found) / len(expected) if expected else None,
        'clarification_behavior': bool(
            re.search(
                r'which|could you|please (?:specify|provide|confirm)|do you mean|ticket key|ticket number|clarif',
                response,
                re.I,
            )
        )
        if case['expected']['clarification']
        else None,
        'reference_verified': case.get('reference_status') == 'verified',
        'ngrams': reference_metrics.overlap(case['reference'], response),
        'note': 'Token overlap is a descriptive similarity baseline, not factual accuracy. Reference-dependent quality requires human verification.',
    }


async def ragas_scores(
    question,
    response,
    contexts,
    cfg,
    reference=None,
    retrieval_kind='semantic',
    dataset_id='',
    session_id='',
    reference_contexts=None,
    reference_verified=False,
    context_verified=False,
):
    if not contexts:
        return {'status': 'not_applicable', 'reason': 'No retrieved narrative or structured evidence.'}
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        ContextPrecisionWithoutReference,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    judge_trace = (
        telemetry.Trace(
            dataset_id,
            session_id or uuid.uuid4().hex,
            cfg,
            'Score evidence for: ' + question,
            kind='evaluation_judge',
        )
        if dataset_id
        else None
    )

    async def on_request(request):
        request.extensions['agile_started'] = time.monotonic()

    async def on_response(response):
        await response.aread()
        if judge_trace:
            try:
                body = json.loads(response.request.content)
                data = response.json()
                judge_trace.external_model(
                    body,
                    data,
                    time.monotonic() - response.request.extensions.get('agile_started', time.monotonic()),
                    'success' if response.is_success else 'error',
                )
            except (ValueError, TypeError):
                pass

    async_client = AsyncOpenAI(
        base_url=cfg['base'],
        api_key=cfg.get('key') or 'local',
        max_retries=0,
        timeout=45,
        http_client=httpx.AsyncClient(event_hooks={'request': [on_request], 'response': [on_response]}),
    )
    llm = llm_factory(
        cfg.get('wire_model') or cfg['model'], max_retries=1, max_tokens=1800, client=async_client
    )
    window = int(cfg.get('context_window', 32768))
    budget = min(24000, max(2000, int((window - 2048) * 1.2)))
    distinct = list(dict.fromkeys(contexts))
    packet = []
    remaining = budget
    for text in distinct[:8]:
        if remaining <= 0:
            break
        part = text[:remaining]
        packet.append(part)
        remaining -= len(part)
    metrics = {}
    for name, metric, values in [
        (
            'faithfulness',
            Faithfulness(llm=llm),
            {'user_input': question, 'response': response, 'retrieved_contexts': packet},
        ),
        (
            'context_precision',
            ContextPrecisionWithReference(llm=llm)
            if reference_verified
            else ContextPrecisionWithoutReference(llm=llm),
            {'user_input': question, 'reference': reference, 'retrieved_contexts': packet}
            if reference_verified
            else {'user_input': question, 'response': response, 'retrieved_contexts': packet},
        ),
    ]:
        try:
            if name == 'context_precision' and retrieval_kind in {'structured', 'reference_validation'}:
                metrics['context_precision'] = None
                metrics['context_precision_note'] = (
                    'Not applicable: structured query or reference-evidence validation, not ranked agent retrieval.'
                )
                continue
            result = await asyncio.wait_for(metric.ascore(**values), timeout=100)
            score = float(result.value)
            if not math.isfinite(score):
                raise ValueError('Judge returned a non-finite score.')
            metrics[name] = score
        except Exception as exc:
            metrics[name] = None
            metrics[name + '_error'] = clean(str(exc), 300)
    if reference_verified and reference and retrieval_kind != 'reference_validation':
        try:
            result = await asyncio.wait_for(
                ContextRecall(llm=llm).ascore(
                    user_input=question, reference=reference, retrieved_contexts=packet
                ),
                timeout=100,
            )
            value = float(result.value)
            metrics['context_recall'] = value if math.isfinite(value) else None
        except Exception as exc:
            metrics['context_recall'] = None
            metrics['context_recall_error'] = clean(str(exc), 300)
    else:
        metrics['context_recall'] = None
        metrics['context_recall_note'] = (
            'Reference-answer recall needs a verified answer and actual retrieved evidence; it is not scored for reference-only evidence validation.'
        )
    if context_verified and reference_contexts and retrieval_kind != 'reference_validation':
        try:
            import warnings

            from ragas.dataset_schema import SingleTurnSample

            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                from ragas.metrics import NonLLMContextPrecisionWithReference, NonLLMContextRecall
            sample = SingleTurnSample(retrieved_contexts=packet, reference_contexts=reference_contexts[:12])
            metrics['context_text_recall'] = await NonLLMContextRecall().single_turn_ascore(sample)
            metrics[
                'context_text_precision'
            ] = await NonLLMContextPrecisionWithReference().single_turn_ascore(sample)
            metrics['context_text_note'] = (
                'Ragas non-LLM string matching, threshold 0.5; wording and chunk boundaries affect this heuristic.'
            )
        except Exception as exc:
            metrics['context_text_error'] = clean(str(exc), 300)
    else:
        metrics['context_text_note'] = (
            'Direct context matching requires verified reference evidence plus actual retrieved context; it is not scored for reference-only validation.'
        )
    await async_client.close()
    if judge_trace:
        judge_trace.finish(
            'success' if metrics.get('faithfulness') is not None else 'error',
            {'content': json.dumps(metrics), 'skill': 'evaluation'},
        )
    return {
        'status': 'complete'
        if metrics.get('faithfulness') is not None
        and (
            retrieval_kind in {'structured', 'reference_validation'}
            or metrics.get('context_precision') is not None
        )
        else 'partial',
        'metrics': metrics,
        'judge_model': cfg['model'],
        'sampled_contexts': len(packet),
        'context_sample_policy': 'Up to eight distinct evidence packets within the declared model window, capped at 24000 characters. Scores cover the supplied packet only.',
        'context_chars_available': sum(map(len, distinct)),
        'context_chars_scored': sum(map(len, packet)),
        'context_coverage': sum(map(len, packet)) / max(1, sum(map(len, distinct))),
        'retrieval_kind': retrieval_kind,
        'scoring_version': 3,
        'precision_variant': 'with_reference' if reference_verified else 'without_reference',
        'reference_verified': reference_verified,
        'reference_context_verified': context_verified,
        'judge_run_id': judge_trace.id if judge_trace else None,
    }


def pipeline_version():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for file in sorted(root.rglob('*.py')):
        if 'observability' not in file.relative_to(root).parts:
            digest.update(str(file.relative_to(root)).encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


def replay(
    base,
    dataset_id,
    connection_id,
    cases,
    effort='standard',
    use_ragas=False,
    delay=3,
    resume_id=None,
    judge_connection_id=None,
    golden_version=None,
    job_id=None,
    prompt_version_id='',
):
    from ..agent import prompt_versions

    with httpx.Client(timeout=10) as preflight:
        ready = preflight.get(base.rstrip('/') + f'/api/datasets/{dataset_id}/agent/status')
        ready.raise_for_status()
        if ready.json().get('status') != 'ready':
            raise ValueError('Agent index is not ready. Prepare it in Configure before starting evaluation.')
    cfg = connections.resolve(connection_id)
    judge_cfg = connections.resolve(judge_connection_id or connection_id)
    ident = resume_id or uuid.uuid4().hex
    db = store.mongo()
    old = db.agent_evaluations.find_one({'id': ident}) if resume_id else None
    prompt = prompt_versions.get(dataset_id, (old or {}).get('prompt_version_id') or prompt_version_id)
    session = old.get('session_id') if old else None
    doc = {
        'id': ident,
        'dataset_id': dataset_id,
        'prompt_version_id': prompt['id'],
        'prompt_version_number': prompt['number'],
        'prompt_sha256': prompt['sha256'],
        'prompt_snapshot': prompt,
        'connection_id': connection_id,
        'model': cfg['model'],
        'provider': cfg['provider'],
        'status': 'running',
        'started_at': now(),
        'case_count': len(cases),
        'dataset_version': cases[0]['dataset_version'],
        'source_snapshot_sha256': (store.dataset(dataset_id) or {}).get('metadata', {}).get('sha256'),
        'effort': effort,
        'pipeline_version': pipeline_version(),
        'ragas_enabled': use_ragas,
        'judge_connection_id': judge_connection_id or connection_id,
        'judge_model': judge_cfg['model'],
        'source_file': cases[0]['source']['file'],
        'completed': 0,
        'failed': 0,
        'reference_warning': 'Original model responses are provisional unless marked verified by a human.',
    }
    if golden_version:
        doc.update(
            golden_dataset_id=golden_version['dataset_id'],
            golden_version_id=golden_version['id'],
            golden_version_number=golden_version['number'],
            golden_name=golden_version['name'],
            case_snapshot=cases,
            job_id=job_id,
        )
    if not old:
        db.agent_evaluations.insert_one(doc)
    else:
        db.agent_evaluations.update_one({'id': ident}, {'$set': {'status': 'running'}})
    print(json.dumps({'evaluation_id': ident, 'cases': len(cases), 'model': cfg['model']}), flush=True)
    with httpx.Client(timeout=httpx.Timeout(240, connect=10)) as client:
        sessions_by_conversation = {}
        for case in cases:
            conversation_id = case.get('conversation_id', 'conversation-1')
            session = sessions_by_conversation.get(conversation_id)
            previous = db.agent_eval_results.find_one({'evaluation_id': ident, 'case_id': case['id']})
            if previous:
                session = previous.get('session_id', session)
                sessions_by_conversation[conversation_id] = session
                continue
            started = time.monotonic()
            record = {
                'id': uuid.uuid5(uuid.NAMESPACE_URL, ident + case['id']).hex,
                'evaluation_id': ident,
                'case_id': case['id'],
                'case_number': case['case_number'],
                'question': case['question'],
                'reference': case['reference'],
                'reference_status': case['reference_status'],
                'reference_contexts': case.get('reference_contexts', []),
                'context_status': case.get('context_status', 'missing'),
                'context_source': case.get('context_source', ''),
                'golden_version_id': (golden_version or {}).get('id'),
                'golden_dataset_id': (golden_version or {}).get('dataset_id'),
                'conversation_id': conversation_id,
                'model': cfg['model'],
                'started_at': now(),
            }
            try:
                response = client.post(
                    base.rstrip('/') + f'/api/datasets/{dataset_id}/agent/chat',
                    json={
                        'message': case['question'],
                        'connection_id': connection_id,
                        'session_id': session,
                        'effort': effort,
                        'stream': True,
                        'use_page_context': False,
                        'prompt_version_id': prompt['id'],
                    },
                )
                response.raise_for_status()
                events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
                record['run_id'] = next(
                    (e.get('run_id') for e in events if e['event'] in {'error', 'run'} and e.get('run_id')),
                    None,
                )
                error = next((e['message'] for e in events if e['event'] == 'error'), None)
                if error:
                    raise ValueError(error)
                answer = next(e for e in events if e['event'] == 'done')
                session = answer['session_id']
                sessions_by_conversation[conversation_id] = session
                run = db.agent_runs.find_one({'id': answer.get('run_id')}, {'_id': 0}) or {}
                contexts = run.get('retrieved_contexts', [])
                if not contexts:
                    contexts = [
                        t.get('result', '')
                        for t in run.get('tool_calls', [])
                        if t['tool'] not in {'plan_investigation', 'calculator', 'get_project_context'}
                        and t.get('ok')
                    ][:3]
                scores = deterministic_metrics(case, answer['content'], answer.get('sources', []))
                try:
                    ragas = (
                        asyncio.run(
                            ragas_scores(
                                case['question'],
                                answer['content'],
                                contexts,
                                judge_cfg,
                                case['reference'],
                                (
                                    'semantic'
                                    if any(
                                        t['tool']
                                        in {'search_tickets', 'investigate_tickets', 'explore_graph'}
                                        for t in run.get('tool_calls', [])
                                    )
                                    else 'structured'
                                ),
                                dataset_id,
                                session or '',
                                case.get('reference_contexts', []),
                                case.get('reference_status') == 'verified',
                                case.get('context_status') == 'verified',
                            )
                        )
                        if use_ragas
                        else {
                            'status': 'not_run',
                            'reason': 'Run with --ragas to invoke the selected judge model.',
                        }
                    )
                except Exception as scoring_error:
                    ragas = {'status': 'error', 'reason': clean(str(scoring_error), 500)}
                record.update(
                    status='success',
                    response=answer['content'],
                    run_id=answer.get('run_id'),
                    session_id=session,
                    generation_latency_ms=run.get('latency_ms'),
                    sources=answer.get('sources', []),
                    retrieved_contexts=contexts[:20],
                    metrics=scores,
                    ragas=ragas,
                )
                langfuse_bridge.evaluation_scores(answer.get('run_id'), ragas)
            except Exception as exc:
                message = str(exc)
                if isinstance(exc, httpx.HTTPStatusError):
                    try:
                        message = str(exc.response.json().get('detail', message))
                    except ValueError:
                        pass
                record.update(
                    status='error',
                    error=clean(message, 700),
                    metrics={},
                    ragas={'status': 'not_run', 'reason': 'Answer generation failed.'},
                )
            record.update(latency_ms=round((time.monotonic() - started) * 1000), finished_at=now())
            db.agent_eval_results.replace_one({'id': record['id']}, record, upsert=True)
            completed = db.agent_eval_results.count_documents({'evaluation_id': ident, 'status': 'success'})
            failed = db.agent_eval_results.count_documents({'evaluation_id': ident, 'status': 'error'})
            db.agent_evaluations.update_one(
                {'id': ident},
                {
                    '$set': {
                        'completed': completed,
                        'failed': failed,
                        'session_id': session,
                        'updated_at': now(),
                    }
                },
            )
            print(
                json.dumps(
                    {
                        'case': case['case_number'],
                        'status': record['status'],
                        'latency_ms': record['latency_ms'],
                        'ragas': record['ragas'].get('status'),
                        'error': record.get('error'),
                    }
                ),
                flush=True,
            )
            if delay:
                time.sleep(delay)
    db.agent_evaluations.update_one({'id': ident}, {'$set': {'status': 'complete', 'finished_at': now()}})
    return ident


def rescore(evaluation_id, delay=20):
    db = store.mongo()
    evaluation = db.agent_evaluations.find_one({'id': evaluation_id})
    if not evaluation:
        raise ValueError('Evaluation run not found.')
    cfg = connections.resolve(evaluation.get('judge_connection_id') or evaluation['connection_id'])
    for result in db.agent_eval_results.find({'evaluation_id': evaluation_id, 'status': 'success'}).sort(
        'case_number', 1
    ):
        run = db.agent_runs.find_one({'id': result.get('run_id')}) or {}
        kind = (
            'semantic'
            if any(
                t['tool'] in {'search_tickets', 'investigate_tickets', 'explore_graph'}
                for t in run.get('tool_calls', [])
            )
            else 'structured'
        )
        scores = asyncio.run(
            ragas_scores(
                result['question'],
                result['response'],
                result.get('retrieved_contexts', []),
                cfg,
                result.get('reference'),
                kind,
                evaluation['dataset_id'],
                result.get('session_id', ''),
                result.get('reference_contexts', []),
                result.get('reference_status') == 'verified',
                result.get('context_status') == 'verified',
            )
        )
        db.agent_eval_results.update_one(
            {'id': result['id']},
            {'$set': {'ragas': scores}, '$push': {'ragas_history': result.get('ragas', {})}},
        )
        langfuse_bridge.evaluation_scores(result.get('run_id'), scores)
        print(
            json.dumps({'rescored_case': result['case_number'], 'status': scores.get('status')}), flush=True
        )
        if delay:
            time.sleep(delay)


@router.get('/runs')
def evaluations():
    return list(
        store.mongo()
        .agent_evaluations.find({}, {'_id': 0, 'case_snapshot': 0, 'prompt_snapshot': 0})
        .sort('started_at', -1)
        .limit(100)
    )


@router.get('/cases')
def evaluation_cases(version: str = ''):
    return list(
        store.mongo()
        .agent_eval_cases.find({'dataset_version': version} if version else {}, {'_id': 0, 'history': 0})
        .sort('case_number', 1)
        .limit(500)
    )


@router.get('/runs/{evaluation_id}')
def evaluation_run(evaluation_id: str):
    db = store.mongo()
    run = db.agent_evaluations.find_one({'id': evaluation_id}, {'_id': 0})
    if not run:
        raise HTTPException(404, 'Evaluation not found.')
    results = list(
        db.agent_eval_results.find({'evaluation_id': evaluation_id}, {'_id': 0}).sort('case_number', 1)
    )

    for result in results:
        ngrams = reference_metrics.ensure_metrics(result)
        result['metric_story'] = reference_metrics.narrative(
            ngrams, result.get('ragas'), result.get('reference_status') == 'verified'
        )
        trace = (
            db.agent_runs.find_one(
                {'id': result.get('run_id')},
                {'latency_ms': 1, 'usage': 1, 'model_call_count': 1, 'tool_call_count': 1, 'cost_usd': 1},
            )
            or {}
        )
        result['generation_latency_ms'] = result.get('generation_latency_ms') or trace.get('latency_ms')
        result['usage'] = trace.get('usage', {})
        result['model_calls'] = trace.get('model_call_count')
        result['tool_calls'] = trace.get('tool_call_count')
        result['cost_usd'] = trace.get('cost_usd')

    def average(values):
        found = [
            v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        ]
        return sum(found) / len(found) if found else None

    return {
        **run,
        'results': results,
        'summary': {
            'mean_answer_latency_ms': average([r.get('generation_latency_ms') for r in results]),
            'known_cost_usd': sum(r.get('cost_usd') or 0 for r in results),
            'human_score': average([r.get('human', {}).get('score') for r in results]),
            'reviewed': sum(bool(r.get('human')) for r in results),
            'faithfulness': average(
                [r.get('ragas', {}).get('metrics', {}).get('faithfulness') for r in results]
            ),
            'context_recall': average(
                [r.get('ragas', {}).get('metrics', {}).get('context_recall') for r in results]
            ),
            'context_precision': average(
                [r.get('ragas', {}).get('metrics', {}).get('context_precision') for r in results]
            ),
            'reference_token_f1': average([r.get('metrics', {}).get('reference_token_f1') for r in results]),
            'bleu': {
                str(n): average(
                    [r.get('metrics', {}).get('ngrams', {}).get('bleu', {}).get(str(n)) for r in results]
                )
                for n in range(2, 6)
            },
            'rouge': {
                str(n): average(
                    [
                        (r.get('metrics', {}).get('ngrams', {}).get('rouge', {}).get(str(n)) or {}).get('f1')
                        for r in results
                    ]
                )
                for n in range(2, 6)
            },
            'rouge_l': average(
                [r.get('metrics', {}).get('ngrams', {}).get('rouge_l', {}).get('f1') for r in results]
            ),
            'success_rate': sum(r['status'] == 'success' for r in results) / len(results)
            if results
            else None,
        },
    }


class HumanReview(BaseModel):
    score: int = Field(ge=1, le=5)
    feedback: str = Field(default='', max_length=300)
    reference_verified: bool = False
    corrected_reference: str | None = Field(default=None, max_length=12000)


@router.post('/results/{result_id}/review')
def human_review(result_id: str, body: HumanReview):
    db = store.mongo()
    result = db.agent_eval_results.find_one({'id': result_id})
    if not result:
        raise HTTPException(404, 'Evaluation result not found.')
    review = {
        **body.model_dump(exclude={'corrected_reference'}),
        'feedback': clean(body.feedback, 300),
        'reviewed_at': now(),
    }
    new_version = None
    from . import evaluation_datasets as golden

    run = db.agent_evaluations.find_one({'id': result['evaluation_id']}) or {}
    version_id = result.get('golden_version_id')
    if not version_id and run.get('golden_dataset_id'):
        version_id = golden.dataset(run['golden_dataset_id'])['head_version_id']
    if body.reference_verified and version_id:
        base = golden.version(version_id)
        latest = golden.version(golden.dataset(base['dataset_id'])['head_version_id'])
        original = next((c for c in base['cases'] if c['id'] == result['case_id']), None)
        current = next((c for c in latest['cases'] if c['id'] == result['case_id']), None)
        if (
            not original
            or not current
            or any(original.get(k) != current.get(k) for k in ['question', 'reference', 'reference_contexts'])
        ):
            raise HTTPException(
                409,
                'This case changed after the test. Review its latest golden version in the dataset editor.',
            )
        if result.get('question') and result['question'] != current['question']:
            raise HTTPException(
                409, 'The question changed after this test. Update the reference in the dataset editor.'
            )
        base = latest
        cases = [dict(c) for c in base['cases']]
        for case in cases:
            if case['id'] == result['case_id']:
                case.update(
                    reference_status='verified', reference=body.corrected_reference or case['reference']
                )
        new_version = golden.publish(
            base['dataset_id'],
            golden.DatasetWrite(
                name=base['name'],
                notes=base['notes'],
                ticket_dataset_id=base['ticket_dataset_id'],
                cases=cases,
                base_version_id=base['id'],
                change_note='Reference verified during human review',
            ),
        )
    elif body.reference_verified:
        change = {'reference_status': 'verified'}
        if body.corrected_reference is not None:
            change['reference'] = body.corrected_reference
        db.agent_eval_cases.update_one({'id': result['case_id']}, {'$set': change})
        db.agent_eval_results.update_one(
            {'id': result_id}, {'$set': {**change, 'metrics.reference_metrics_stale': True}}
        )
    if new_version:
        review['verified_reference_version_id'] = new_version['id']
    db.agent_eval_results.update_one({'id': result_id}, {'$set': {'human': review}})
    try:
        if result.get('run_id'):
            langfuse_bridge.score(result['run_id'], 'human_evaluation', body.score, body.feedback)
    except Exception:
        pass
    return {
        'saved': True,
        'new_version_id': (new_version or {}).get('id'),
        'new_version_number': (new_version or {}).get('number'),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--document', default=str(Path.home() / 'Downloads/Conversation.docx'))
    parser.add_argument('--dataset', default='')
    parser.add_argument('--connection', default='')
    parser.add_argument('--judge-connection', default='')
    parser.add_argument('--base', default='http://127.0.0.1:8000')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--effort', choices=['low', 'standard', 'high'], default='standard')
    parser.add_argument('--delay', type=float, default=3)
    parser.add_argument('--ragas', action='store_true')
    parser.add_argument('--import-only', action='store_true')
    parser.add_argument('--resume', default='')
    parser.add_argument('--score-run', default='')
    args = parser.parse_args()
    if args.score_run:
        rescore(args.score_run, args.delay)
        return
    cases = import_document(args.document)
    folder = Path('resources/evaluation')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'conversation-cases.jsonl').write_text(
        '\n'.join(json.dumps(c, ensure_ascii=False) for c in cases) + '\n'
    )
    print(f'Imported all {len(cases)} cases from {Path(args.document).name}', flush=True)
    if args.import_only:
        return
    dataset = args.dataset or (store.mongo().workspace_settings.find_one({'id': 'workspace'}) or {}).get(
        'active_dataset'
    )
    if not dataset:
        latest = store.mongo().datasets.find_one({'status': 'ready'}, sort=[('imported_at', -1)])
        dataset = latest['id'] if latest else None
    if not dataset:
        raise ValueError('Import the source project before running evaluation.')
    connection = args.connection or next(
        (c['id'] for c in connections.choices() if c['provider'] == 'gemini'), None
    )
    if not connection:
        raise ValueError('Configure a Gemini connection, or specify --connection.')
    from . import evaluation_datasets as golden

    golden.adopt_legacy()
    golden_id = 'conversation-' + cases[0]['dataset_version'][:24]
    saved = golden.dataset(golden_id)
    golden_version = golden.version(saved['head_version_id'])
    if args.resume:
        old = store.mongo().agent_evaluations.find_one({'id': args.resume}) or {}
        if old.get('golden_version_id'):
            golden_version = golden.version(old['golden_version_id'])
    cases = golden.replay_cases(golden_version)
    replay(
        args.base,
        dataset,
        connection,
        cases[: args.limit] if args.limit else cases,
        args.effort,
        args.ragas,
        args.delay,
        args.resume or None,
        args.judge_connection or None,
        golden_version=golden_version,
    )


if __name__ == '__main__':
    main()
