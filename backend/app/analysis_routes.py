"""Deterministic planning reports and streamed AI proposals inside product screens."""

import json
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import planning, store
from .agent import connections, context_budget, conversation, grounding, index, provider
from .agent.tools import Context
from .observability import telemetry

router = APIRouter(prefix='/api/datasets/{dataset_id}', tags=['Planning and AI analysis'])


def check(dataset_id):
    row = store.dataset(dataset_id)
    if not row or row['status'] != 'ready':
        raise HTTPException(404, 'Choose a completed import first.')


@router.get('/planning/settings')
def settings(dataset_id: str, project: str):
    check(dataset_id)
    return planning.saved(dataset_id, project)


@router.put('/planning/settings')
def save_settings(dataset_id: str, config: planning.PlanningConfig):
    check(dataset_id)
    try:
        return planning.save(dataset_id, config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/planning/report')
def report(dataset_id: str, config: planning.PlanningConfig):
    check(dataset_id)
    try:
        return planning.report(dataset_id, config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class AnalysisRequest(BaseModel):
    kind: Literal['ticket', 'backlog']
    key: str = Field(default='', max_length=100)
    config: planning.PlanningConfig | None = None
    connection_id: str | None = Field(default=None, max_length=160)
    review_id: str = Field(default='', max_length=100)
    batch_limit: int = Field(default=20, ge=1, le=100)


class Cancelled(Exception):
    pass


def context(dataset_id, request, project='', emit=None):
    return Context(
        dataset_id,
        project,
        on_event=emit,
        retrieval_cache=request.app.state.retrieval_cache,
        skill_catalog=request.app.state.skill_catalog,
    )


def run_ticket(dataset_id, body, request, cfg, emit):
    ctx = context(dataset_id, request, emit=emit)
    question = f'Explain {body.key}: give a concise summary of the actual requirements and evidence, then concrete suggestions for a fix or next steps. Compare the similar-ticket evidence supplied, distinguish suggestions from verified facts, cover relevant acceptance criteria/relationships and unread attachments. Do not assume code or attachment contents are available. Use at most 180 words: lead with two sentences about purpose/current state, then up to four actionable bullets. Avoid repeated Summary/Evidence/Insight sections. Mention attachments only when ticket_context lists one. Use exact ticket titles when naming a similar ticket.'
    conversation.resolve(ctx, question)
    detail = ctx.call('get_ticket', {'reference': body.key})
    if 'ticket' not in detail:
        raise ValueError('Choose a ticket included in this import.')
    ctx.feature_evidence = grounding.similar_ticket_evidence(ctx, detail, cfg)
    answer, _ = provider.run(ctx, question, [], [body.key], False, body.connection_id)
    return {
        'content': answer,
        'model': cfg['model'],
        'sources': list(ctx.citations.values()),
        'tools': ctx.trace,
        'groups': [],
        'assignments': [],
    }


def compact_backlog_evidence(evidence):
    result = dict(evidence)
    people = evidence['people']
    result['people'] = [
        {
            key: person[key]
            for key in (
                'name',
                'roles',
                'eligible',
                'unit',
                'budget',
                'allocation_room',
                'known_load',
                'usual_point_size',
            )
        }
        for person in people[:2]
    ]
    result['people_coverage'] = {
        'shown': min(2, len(people)),
        'total': len(people),
        'note': 'A subset of people for this small context; do not infer other people are unavailable.',
    }
    for field in ('batch_tickets', 'current_batch'):
        if field in result:
            result[field] = [
                {
                    key: value
                    for key, value in ticket.items()
                    if key
                    in {
                        'key',
                        'summary',
                        'assignee',
                        'priority',
                        'estimates',
                        'readiness',
                        'next_step',
                        'assessment',
                        'narrative_excerpt',
                    }
                }
                for ticket in result[field]
            ]
    if 'report' in result:
        report = result['report']
        result['report'] = {
            'scope_label': report['scope_label'],
            'metrics': {
                key: report['metrics'][key]
                for key in (
                    'backlog_tickets',
                    'estimated_tickets',
                    'missing_estimates',
                    'active_developers',
                    'known_estimate',
                    'missing_priorities',
                )
            },
            'priorities': report['priorities'],
            'forecast': report['forecast'],
        }
        for field in ('missing_estimate_tickets', 'refinement_examples', 'selected_priority_examples'):
            result.pop(field, None)
    else:
        result.pop('metrics', None)
        result.pop('config', None)
    return result


def run_backlog(dataset_id, body, request, cfg, emit):
    report = planning.report(dataset_id, body.config)
    keys = [ticket['key'] for ticket in report['tickets']]
    previous = review_state(dataset_id, body, report)
    start_offset = previous.get('next_offset', 0)
    review_id = previous.get('id') or uuid.uuid4().hex
    limits = context_budget.settings(cfg)
    end_offset = min(len(keys), start_offset + min(body.batch_limit, limits['ticket_max']))
    review_tickets = report['tickets'][start_offset:end_offset]
    groups = dict(previous.get('groups', {}))
    assignments = list(previous.get('assignments', []))
    reserved = dict(previous.get('reserved', {}))
    trace = []
    assessments = {}
    narrative_by_key = {}
    people = [
        {
            key: person[key]
            for key in (
                'name',
                'active',
                'eligible',
                'roles',
                'headroom',
                'allocation_room',
                'budget',
                'unit',
                'available',
                'known_load',
                'missing_estimates',
                'typical_types',
                'developer',
                'assigned_total',
                'unfinished_total',
                'usual_point_size',
                'average_points_per_sprint',
                'average_points_sprint_count',
                'sprint_point_unestimated_tickets',
                'point_estimated_tickets',
                'point_unestimated_tickets',
                'common_point_sizes',
            )
        }
        | {'recent_sprint_work': person['sprint_work'][:3]}
        for person in sorted(
            report['people'], key=lambda person: (not person['eligible'], -(person['allocation_room'] or 0))
        )
    ]

    def relevant_people(tickets):
        owners = {ticket['assignee'].casefold() for ticket in tickets if ticket['assignee']}
        selected = [person for person in people if person['name'].casefold() in owners]
        selected += [person for person in people if person['eligible'] and person not in selected][:12]
        return selected

    batch_size = 1 if limits['window'] < 8192 else 8
    for start in range(0, len(review_tickets), batch_size):
        batch = review_tickets[start : start + batch_size]
        emit(
            'activity',
            {
                'message': f'Reviewing backlog tickets {start_offset + start + 1}–{start_offset + start + len(batch)} of {len(keys)} and checking role fit.'
            },
        )
        ctx = context(
            dataset_id,
            request,
            body.config.project,
            lambda event, data: emit(event, data) if event != 'text_delta' else None,
        )
        ctx.planning_report, ctx.planning_keys, ctx.planning_reserved, ctx.planning_plan = (
            report,
            [ticket['key'] for ticket in batch],
            reserved,
            None,
        )
        ctx.planning_assessment_required = True
        batch_evidence = []
        for ticket in batch:
            raw = store.issue(dataset_id, ticket['key'])['details']
            narrative = index.ticket_document(ctx.by_key[ticket['key'].casefold()], raw['fields'])
            narrative_by_key[ticket['key']] = narrative[:2400]
            batch_evidence.append(
                {**ticket, 'narrative_excerpt': narrative[:2400], 'excerpt_truncated': len(narrative) > 2400}
            )
        ctx.feature_evidence = {
            'required_ticket_keys': ctx.planning_keys,
            'assignment_candidate_keys': [
                ticket['key']
                for ticket in batch
                if not ticket['assignee']
                and ticket['priority_finalized']
                and any(value is not None for value in ticket['estimates'].values())
                and ticket['estimate_counted']
            ],
            'metrics': report['metrics'],
            'config': report['config'],
            'allocation_basis': report['allocation_basis'],
            'people': relevant_people(batch),
            'people_coverage': {
                'total': len(people),
                'note': 'All batch owners plus up to twelve eligible candidates. Omitted profiles are not evidence of unavailability.',
            },
            'already_reserved_capacity': reserved,
            'previous_category_names': list(groups),
            'batch_tickets': batch_evidence,
        }
        if limits['window'] < 8192:
            ctx.feature_evidence = compact_backlog_evidence(ctx.feature_evidence)
        question = 'Review this batch using supplied people roles, typical work and story sizes. Call record_backlog_plan for EVERY required key, group by work theme, and suggest owners only when supplied role evidence, estimates and remaining per-sprint capacity justify them. Assigned gaps need assignee refinement; unassigned gaps need triage. Empty assignments are valid. Snapshot sprint totals are not historical velocity. No Jira changes.'
        ctx.question = question
        provider.run(ctx, question, [], [], False, body.connection_id)
        if ctx.planning_plan is None:
            raise provider.ModelError(
                'The model did not produce a complete validated plan. Retry or choose a smaller sprint scope.'
            )
        for group in ctx.planning_plan['groups']:
            label = next(
                (name for name in groups if name.casefold() == group['name'].casefold()), group['name']
            )
            groups.setdefault(label, []).extend(group['keys'])
        assessments.update(ctx.planning_plan.get('assessments', {}))
        assignments.extend(ctx.planning_plan['assignments'])
        reserved = ctx.planning_reserved
        trace.extend(ctx.trace)
    ctx = context(dataset_id, request, body.config.project, emit)
    coverage = {
        'reviewed': end_offset,
        'total': len(keys),
        'remaining': len(keys) - end_offset,
        'batch_start': start_offset + 1 if review_tickets else 0,
        'batch_count': len(review_tickets),
        'has_more': end_offset < len(keys),
    }
    summary_groups = [
        {'name': name, 'count': len(value), 'example_keys': value[:4]} for name, value in groups.items()
    ]
    ctx.feature_evidence = {
        'report': {
            key: report[key]
            for key in (
                'config',
                'scope_label',
                'metrics',
                'statuses',
                'priorities',
                'types',
                'notes',
                'readiness',
                'forecast',
                'allocation_basis',
            )
        },
        'people': relevant_people(review_tickets),
        'people_coverage': {
            'total': len(people),
            'note': 'Batch owners plus a bounded selection of eligible candidates.',
        },
        'review_coverage': coverage,
        'current_batch': [
            {
                **ticket,
                'assessment': assessments.get(ticket['key'], ''),
                'narrative_excerpt': narrative_by_key.get(ticket['key'], '')[:600],
            }
            for ticket in review_tickets
        ],
        'batch_readiness': {
            name: sum(ticket['readiness'] == name for ticket in review_tickets)
            for name in ('ready', 'needs_owner', 'owner_refinement', 'triage', 'parent_tracking')
        },
        'batch_missing_estimates': sum(
            ticket['estimate_counted'] and ticket['estimate'] is None for ticket in review_tickets
        ),
        'batch_missing_priorities': sum(not ticket['priority_finalized'] for ticket in review_tickets),
        'missing_estimate_tickets': [
            ticket for ticket in review_tickets if ticket['estimate_counted'] and ticket['estimate'] is None
        ][:12],
        'refinement_examples': [
            ticket for ticket in review_tickets if ticket['readiness'] in {'triage', 'owner_refinement'}
        ][:12],
        'selected_priority_examples': [
            ticket for ticket in review_tickets if ticket['priority'] in body.config.focus_priorities
        ][:8],
        'ai_work_categories': summary_groups,
        'proposed_allocations': assignments[:24],
        'assignment_count': len(assignments),
        'capacity_reserved': reserved,
    }
    citation_keys = (
        {
            ticket['key']
            for ticket in ctx.feature_evidence['missing_estimate_tickets']
            + ctx.feature_evidence['selected_priority_examples']
            + ctx.feature_evidence['refinement_examples']
        }
        | {ticket['key'] for ticket in review_tickets}
        | {item['key'] for item in assignments[-24:]}
    )
    for key in sorted(citation_keys):
        ctx.cite(ctx.by_key[key.casefold()], 'Verified backlog snapshot metadata')
    if limits['window'] < 8192:
        ctx.feature_evidence = compact_backlog_evidence(ctx.feature_evidence)
    question = 'Assess this reviewed batch in 150–220 words using the per-ticket findings. Start with batch count and readiness/missing-input counts (not whole-backlog totals). Identify the 3–5 most useful concrete actions, with ticket references and existing assignees or evidence-backed suggested owners. Explain the actual work and why to act, not general planning rules. Include ready work when present; state if no allocation is justified and the specific missing inputs. At most one short question for a real unresolved decision. Do not repeat the UI coverage footer, generic capacity caveats, or internal terms like has_more. Do not claim all backlog work was assessed. No Jira changes.'
    ctx.question = question
    answer, _ = provider.run(ctx, question, [], [], False, body.connection_id)
    state = {
        'id': review_id,
        'dataset_id': dataset_id,
        'fingerprint': report['fingerprint'],
        'connection_id': body.connection_id,
        'next_offset': end_offset,
        'groups': groups,
        'assignments': assignments,
        'reserved': reserved,
        'updated_at': datetime.now(timezone.utc),
    }
    if previous:
        saved = store.mongo().backlog_reviews.replace_one(
            {'id': review_id, 'next_offset': start_offset}, state
        )
        if not saved.matched_count:
            raise ValueError('This review advanced in another request. Start a new review to refresh it.')
    else:
        store.mongo().backlog_reviews.insert_one(state)
    return {
        'content': answer,
        'model': cfg['model'],
        'sources': list(ctx.citations.values()),
        'tools': trace + ctx.trace,
        'groups': [{'name': name, 'keys': value} for name, value in groups.items()],
        'assignments': assignments,
        'fingerprint': report['fingerprint'],
        'review_id': review_id,
        'coverage': coverage,
        'assessments': [
            {**ticket, 'assessment': assessments.get(ticket['key'], '')} for ticket in review_tickets
        ],
    }


def review_state(dataset_id, body, report):
    if not body.review_id:
        return {}
    state = store.mongo().backlog_reviews.find_one({'id': body.review_id, 'dataset_id': dataset_id})
    if not state or state['fingerprint'] != report['fingerprint']:
        raise ValueError('The backlog or planning rules changed. Start a new AI review for this report.')
    if state['connection_id'] != body.connection_id:
        raise ValueError('The model changed. Start a new AI review with the selected connection.')
    if state['next_offset'] >= len(report['tickets']):
        raise ValueError(
            'All tickets in this backlog have already been reviewed. Start a new review if needed.'
        )
    return state


@router.post('/analysis')
def analyze(dataset_id: str, body: AnalysisRequest, request: Request):
    check(dataset_id)
    try:
        cfg = connections.resolve(body.connection_id)
        if not cfg['configured']:
            raise ValueError('Connect a model in Sprint Agent → Configure before generating AI analysis.')
        index.require_ready(dataset_id)
        if body.kind == 'ticket' and not store.issue(dataset_id, body.key):
            raise ValueError('Ticket not found in this import.')
        if body.kind == 'backlog':
            if body.config is None:
                raise ValueError('Configure the backlog report first.')
            review_state(dataset_id, body, planning.report(dataset_id, body.config))
    except (ValueError, index.RetrievalError) as exc:
        raise HTTPException(422, str(exc)) from exc

    def events():
        output, stop = queue.Queue(maxsize=128), threading.Event()

        def emit(event, data):
            trace = telemetry.CURRENT.get()
            if trace:
                trace.event(event, data)
            while not stop.is_set():
                try:
                    output.put({'event': event, **data}, timeout=0.25)
                    return
                except queue.Full:
                    continue
            raise Cancelled()

        def work():
            trace = telemetry.Trace(
                dataset_id,
                body.review_id or uuid.uuid4().hex,
                cfg,
                ('Review backlog batch' if body.kind == 'backlog' else 'Explain ticket ' + body.key),
                kind=body.kind + '_analysis',
            )
            result = None
            status, error = 'cancelled', ''
            try:
                emit(
                    'activity',
                    {'message': 'Reading saved project guidance, metadata and relevant ticket context.'},
                )
                result = (
                    run_ticket(dataset_id, body, request, cfg, emit)
                    if body.kind == 'ticket'
                    else run_backlog(dataset_id, body, request, cfg, emit)
                )
                result['run_id'] = trace.id
                status = 'success'
                emit('done', result)
            except Cancelled:
                pass
            except Exception as exc:
                status, error = 'error', str(exc)
                if not stop.is_set():
                    emit(
                        'error',
                        {
                            'message': str(exc)[:500]
                            if isinstance(exc, (ValueError, provider.ModelError, index.RetrievalError))
                            else 'Analysis could not finish. Retry after checking the model connection.'
                        },
                    )
            finally:
                trace.finish(status, result, error)
                if not stop.is_set():
                    output.put(None)

        threading.Thread(target=work, daemon=True).start()
        try:
            while True:
                try:
                    item = output.get(timeout=10)
                except queue.Empty:
                    yield json.dumps({'event': 'heartbeat'}) + '\n'
                    continue
                if item is None:
                    break
                yield json.dumps(item) + '\n'
        finally:
            stop.set()

    return StreamingResponse(
        events(),
        media_type='application/x-ndjson',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )
