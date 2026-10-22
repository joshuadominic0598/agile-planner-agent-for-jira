"""Agent HTTP boundary, scoped persisted conversations, and index lifecycle."""

import json
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import store
from ..observability import telemetry
from . import (
    connections,
    conversation,
    guardrails,
    history_store,
    index,
    preview,
    project_context,
    provider,
    reference_context,
    scope_planner,
    turn_control,
)
from .config import model_config
from .embedding_profiles import PROFILES
from .tools import Context

router = APIRouter(prefix='/api/datasets/{dataset_id}/agent', tags=['Sprint Agent'])
workspace_router = APIRouter(prefix='/api/agent', tags=['Jira conversations'])
# Bounded lock pool. Single API worker, matching the existing import lifecycle.
LOCKS = [threading.Lock() for _ in range(64)]


def check(dataset_id, project=''):
    data = store.dataset(dataset_id)
    if not data:
        raise HTTPException(404, 'Import a Jira CSV before opening the agent.')
    if data['status'] != 'ready':
        raise HTTPException(409, 'Agent unavailable until the CSV has finished processing.')
    if project and not store.summaries(dataset_id, project):
        raise HTTPException(404, 'Project not found in this import.')
    return data


@router.get('/status')
def status(dataset_id: str):
    check(dataset_id)
    config = model_config()
    embedding = index.dataset_embedding_config(dataset_id)
    options = connections.choices()
    if options:
        config = {
            **config,
            'configured': True,
            'provider': options[0]['provider'],
            'model': options[0]['model'],
            'web_available': options[0]['web_available'],
        }
    return {
        **index.status(dataset_id),
        'model': {
            'available': config['configured'],
            'provider': config['provider'],
            'name': config['model'],
            'web_available': config['web_available'],
        },
        'choices': options,
        'embedding': {
            'provider': embedding['provider'],
            'model': embedding['model'],
            'preset': embedding['preset'],
            'private_local': bool(embedding.get('ollama')),
            'chunk_characters': embedding['chunk_characters'],
            'chunk_overlap': embedding['chunk_overlap'],
        },
        'note': (
            'Private embeddings run in local Ollama. AI answers use your selected chat connection; choose a local chat model to keep the entire workflow private.'
            if embedding.get('ollama')
            else 'Ticket context is sent to the configured model provider only in AI mode. External embeddings send indexed ticket text to the configured embedding provider.'
        ),
    }


class IndexRequest(BaseModel):
    embedding_preset: Literal['small', 'large', 'lexical'] | None = None


@workspace_router.get('/embedding-options')
def embedding_options():
    return {'options': [{'id': key, **profile} for key, profile in PROFILES.items()]}


@router.post('/index', status_code=202)
def prepare(dataset_id: str, background: BackgroundTasks, request: IndexRequest | None = None):
    check(dataset_id)
    try:
        reserved = index.reserve(dataset_id, request.embedding_preset if request else None)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if reserved:
        background.add_task(index.build, dataset_id)
    else:
        raise HTTPException(
            409, 'An index build is already running. Wait for it to finish before changing models.'
        )
    return {'status': 'building', 'message': 'Preparing vector, keyword and graph retrieval.'}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    project: str = Field(default='', max_length=100)
    sprint: str = Field(default='', max_length=200)
    active_sprint: str = Field(default='', max_length=200)
    session_id: str | None = Field(default=None, max_length=40)
    attachments: list[str] = Field(default_factory=list, max_length=8)
    mode: Literal['auto', 'ai', 'retrieval'] = 'auto'
    allow_web: bool = False
    connection_id: str | None = Field(default=None, max_length=160)
    prompt_version_id: str = Field(default='', max_length=100)
    stream: bool = False
    request_id: str = Field(default='', max_length=64, pattern=r'^[A-Za-z0-9_-]*$')
    page: str = Field(default='', max_length=80)
    page_ticket: str = Field(default='', max_length=100)
    skill: Literal['auto', 'sprint', 'project', 'backlog', 'employee'] = 'auto'
    reset_context: bool = False
    use_page_context: bool = True
    use_conversation_context: bool = True
    effort: Literal['low', 'standard', 'high'] = 'standard'


def session(dataset_id, project, session_id):
    row = history_store.session(session_id)
    if not row or row['dataset_id'] != dataset_id:
        raise HTTPException(404, 'Conversation not found in this CSV scope. Start a new chat.')


def messages(session_id, before_id=None, limit=60):
    return history_store.messages(session_id, before_id, limit)


def memory(dataset_id, session_id):
    return history_store.memory(dataset_id, session_id)


@router.get('/sessions')
def sessions(
    dataset_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=50)
):
    check(dataset_id)
    return list_sessions(dataset_id, offset, limit)


def list_sessions(dataset_id, offset, limit):
    return history_store.list_sessions(dataset_id, offset, limit)


@workspace_router.get('/conversations')
def workspace_sessions(offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=50)):
    return list_sessions(None, offset, limit)


@router.get('/sessions/{session_id}')
def history(
    dataset_id: str,
    session_id: str,
    project: str = Query(default='', max_length=100),
    before_id: int | None = Query(default=None, ge=1),
):
    check(dataset_id)
    session(dataset_id, project, session_id)
    page = messages(session_id, before_id)
    for item in page:
        if item['role'] == 'assistant' and not item.get('run_id'):
            run_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f'agileplanner:{dataset_id}:{session_id}:{item["id"]}'
            ).hex
            prior_user = next(
                (m['content'] for m in reversed(page[: page.index(item)]) if m['role'] == 'user'), ''
            )
            store.mongo().agent_runs.update_one(
                {'id': run_id},
                {
                    '$setOnInsert': {
                        'id': run_id,
                        'dataset_id': dataset_id,
                        'session_id': session_id,
                        'status': 'legacy',
                        'started_at': item['created_at'],
                        'question': prior_user,
                        'response': item['content'],
                        'model': item.get('model', ''),
                        'usage': {},
                        'context': {},
                        'feedback': {},
                        'note': 'Historical answer; telemetry was not recorded.',
                    }
                },
                upsert=True,
            )
            store.mongo().agent_messages.update_one({'id': item['id']}, {'$set': {'payload.run_id': run_id}})
            item['run_id'] = run_id
    oldest = page[0]['id'] if page else None
    more = history_store.has_older(session_id, oldest)
    state = memory(dataset_id, session_id) or conversation.empty()
    return {
        'session_id': session_id,
        'messages': page,
        'has_more': more,
        'before_id': oldest,
        'conversation_context': state,
        'context_description': conversation.describe(state),
    }


class Cancelled(Exception):
    pass


def execute(
    dataset_id,
    request,
    context,
    cfg,
    session_id,
    attachments,
    previous,
    stop=None,
    turn=None,
    user_messages=(),
):
    reset = request.reset_context or not request.use_conversation_context
    boundary = next(
        (
            i
            for i in range(len(previous) - 1, -1, -1)
            if previous[i]['role'] == 'user' and previous[i].get('context_reset')
        ),
        0,
    )
    previous = [] if reset else previous[boundary:]
    prior = memory(dataset_id, session_id) if request.session_id and not reset else None
    if prior and prior.get('version', 1) < 2:
        recovered = None
        for old_turn in previous:
            if old_turn['role'] == 'user':
                recovered = conversation.resolve(context, old_turn['content'], recovered)
        prior = {
            **prior,
            'version': 2,
            'collection': (recovered or {}).get('collection'),
            'topic': (recovered or {}).get('topic', ''),
        }
    if prior is None and previous:
        page_project, page_sprint = context.project, context.sprint
        for old_turn in previous:
            if old_turn['role'] == 'user':
                hints = old_turn.get('page_hint', {})
                context.project = hints.get('project', page_project) if hints.get('enabled', True) else ''
                context.sprint = hints.get('sprint', page_sprint) if hints.get('enabled', True) else ''
                prior = conversation.resolve(context, old_turn['content'], prior)
        context.project, context.sprint = page_project, page_sprint
    if user_messages:
        for i, item in enumerate(user_messages):
            prior = conversation.resolve(context, item['message'], prior, reset and i == 0)
    else:
        conversation.resolve(context, request.message, prior, reset)
    use_ai = request.mode != 'retrieval'
    if use_ai:
        scope_planner.rebuild(context, request.message, prior, previous, cfg)
    if turn:
        turn.checkpoint()
    reference_context.prepare(
        context, user_messages[-1]['message'] if user_messages else request.message, attachments, previous
    )
    context.emit(
        'context',
        {
            'context_description': conversation.describe(context.conversation_memory),
            'conversation_context': context.conversation_memory,
            'scope_change': context.scope_change,
        },
    )
    context.emit(
        'activity',
        {
            'message': 'Conversation scope: '
            + (conversation.describe(context.conversation_memory) or 'No inherited filters')
        },
    )
    use_ai = request.mode != 'retrieval'
    if use_ai:
        answer, web_sources = provider.run(
            context, request.message, previous, attachments, request.allow_web, request.connection_id
        )
    else:
        answer, web_sources = preview.run(context, request.message, attachments), []
        context.emit('text_delta', {'text': answer})
    if stop and stop.is_set():
        raise Cancelled()
    if turn:
        turn.seal()
    reference_context.remember(context, request.message, answer)
    scope = (
        context.used_scopes[-1]
        if context.used_scopes
        else {'project': 'All projects', 'sprint': 'All issues'}
    )
    generated = use_ai and getattr(context, 'response_mode', 'ai') == 'ai'
    active_trace = telemetry.CURRENT.get()
    payload = {
        'run_id': active_trace.id if active_trace else None,
        'details_markdown': getattr(context, 'details_markdown', ''),
        'conversation_context': context.conversation_memory,
        'context_description': conversation.describe(context.conversation_memory),
        'context_inherited': context.memory_inherited,
        'context_usage': getattr(context, 'context_usage', None),
        'investigation': {
            'effort': request.effort,
            'model_requests': getattr(context, 'model_requests', 0),
            'coverage': getattr(context, 'investigation_result', {}).get('coverage'),
        },
        'fallback_reason': getattr(context, 'fallback_reason', None),
        'attempted_model': getattr(context, 'attempted_model', None),
        'provider_model': cfg.get('wire_model', cfg['model']) if generated else None,
        'model': cfg['model'] if generated else None,
        'connection_id': request.connection_id if generated else None,
        'content': answer,
        'mode': 'ai' if generated else 'retrieval',
        'sources': list(context.citations.values())[:60],
        'tools': context.trace,
        'web_sources': web_sources,
        'snapshot_metrics': context.metrics_used,
        'scope': scope,
        'scopes': context.used_scopes,
        'page_hint': {
            'project': request.project,
            'sprint': request.sprint,
            'view': request.page,
            'ticket': request.page_ticket,
            'enabled': request.use_page_context,
        },
        'attachments': attachments,
        'charts': context.visuals,
        'activity': context.activity,
        'skill': context.skill,
    }
    now = datetime.now(timezone.utc).isoformat()
    history_store.save_turn(
        dataset_id,
        session_id,
        request.project,
        now,
        context.conversation_memory,
        {
            'content': user_messages[-1]['message'] if user_messages else request.message,
            'attachments': user_messages[-1].get('attachments', []) if user_messages else attachments,
            'page_hint': payload['page_hint'],
            'context_reset': reset and not user_messages,
        },
        payload,
        preceding_users=[
            {
                'content': item['message'],
                'attachments': item.get('attachments', []),
                'page_hint': payload['page_hint'],
                'steering': i > 0,
                'context_reset': reset and i == 0,
            }
            for i, item in enumerate(user_messages[:-1])
        ],
    )
    return {'session_id': session_id, **payload}


@router.post('/chat')
def chat(dataset_id: str, request: ChatRequest, http_request: Request):
    check(dataset_id)
    from . import prompt_versions

    prompt = prompt_versions.get(dataset_id, request.prompt_version_id)
    guardrails.validate(request.message, dataset_id, request.session_id or '')
    if not request.message.strip():
        raise HTTPException(422, 'Type a question for the Sprint Agent.')
    try:
        index.require_ready(dataset_id)
    except index.RetrievalError as exc:
        raise HTTPException(409, str(exc)) from exc
    context = Context(
        dataset_id,
        request.project if request.use_page_context else '',
        request.sprint if request.use_page_context else '',
        request.active_sprint if request.use_page_context else '',
        page=request.page if request.use_page_context else '',
        page_ticket=request.page_ticket if request.use_page_context else '',
        retrieval_cache=http_request.app.state.retrieval_cache,
        skill_catalog=http_request.app.state.skill_catalog,
    )
    if context.page_ticket and context.page_ticket.casefold() not in context.by_key:
        raise HTTPException(
            422, 'The open ticket is outside this import. Close the ticket panel or reload it.'
        )
    if context.page_ticket:
        context.page_ticket = context.by_key[context.page_ticket.casefold()]['key']
    context.requested_skill = request.skill
    context.prompt_version_id = prompt['id']
    context.investigation_effort = request.effort
    attachments = list(dict.fromkeys(request.attachments))
    if any(k.casefold() not in context.by_key for k in attachments):
        raise HTTPException(422, 'An attached ticket is outside this CSV. Remove it or import that ticket.')
    attachments = [context.by_key[k.casefold()]['key'] for k in attachments]
    try:
        cfg = connections.resolve(request.connection_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    use_ai = request.mode != 'retrieval'
    if use_ai and not cfg['configured']:
        raise HTTPException(
            503, 'Connect an AI model using Configure to chat. Automatic report responses are disabled.'
        )
    session_id = request.session_id or uuid.uuid4().hex
    if request.session_id:
        session(dataset_id, request.project, session_id)
    previous = messages(session_id) if request.session_id else []
    lock = LOCKS[hash(session_id) % len(LOCKS)]
    if not lock.acquire(blocking=False):
        raise HTTPException(409, 'A response is already being prepared. Wait and try again.')
    if not request.stream:
        trace = None
        try:
            trace = telemetry.Trace(
                dataset_id,
                session_id,
                cfg,
                request.message,
                page={'view': request.page, 'project': request.project, 'sprint': request.sprint},
            )
            trace.persist(prompt_version=telemetry.payload(prompt, 1300000))
            result = execute(dataset_id, request, context, cfg, session_id, attachments, previous)
            trace.finish('success', result)
            return result
        except Exception as exc:
            if trace:
                trace.finish('error', error=str(exc))
            if isinstance(exc, (provider.ModelError, index.RetrievalError)):
                raise HTTPException(502, str(exc)) from exc
            raise
        finally:
            lock.release()

    request_id = request.request_id or uuid.uuid4().hex
    try:
        turn = turn_control.register(request_id, dataset_id)
    except Exception:
        lock.release()
        raise

    def events():
        output = queue.Queue(maxsize=128)
        stop = threading.Event()

        def emit(event, data):
            active_trace = telemetry.CURRENT.get()
            if active_trace:
                active_trace.event(event, data)
            while not stop.is_set():
                try:
                    output.put({'event': event, **data}, timeout=0.25)
                    return
                except queue.Full:
                    continue
            raise Cancelled()

        context.on_event = emit

        def work():
            released = False
            current = context
            trace = None
            result = None
            trace_status, trace_error = 'cancelled', ''
            try:
                trace = telemetry.Trace(
                    dataset_id,
                    session_id,
                    cfg,
                    request.message,
                    request_id=request_id,
                    page={'view': request.page, 'project': request.project, 'sprint': request.sprint},
                )
                trace.persist(prompt_version=telemetry.payload(prompt, 1300000))
                emit('run', {'request_id': request_id, 'session_id': session_id, 'run_id': trace.id})
                while True:
                    followups = turn.snapshot()
                    user_messages = [{'message': request.message, 'attachments': attachments}, *followups]
                    message = (
                        request.message
                        if not followups
                        else (
                            'These user messages arrived during one response. Address compatible requests together; later corrections supersede earlier conflicting requests.\n\n'
                            + '\n\n'.join(
                                f'{i + 1}. {item["message"]}' for i, item in enumerate(user_messages)
                            )
                        )
                    )
                    merged_attachments = list(
                        dict.fromkeys(key for item in user_messages for key in item.get('attachments', []))
                    )
                    if len(merged_attachments) > 8:
                        raise ValueError('Up to eight ticket attachments can be used in one response.')
                    if followups:
                        emit(
                            'steering',
                            {
                                'count': len(followups),
                                'message': 'Applying your new messages and updating the investigation.',
                            },
                        )
                    current = Context(
                        dataset_id,
                        context.project,
                        context.sprint,
                        context.active_sprint,
                        page=context.page,
                        page_ticket=context.page_ticket,
                        retrieval_cache=http_request.app.state.retrieval_cache,
                        skill_catalog=http_request.app.state.skill_catalog,
                    )
                    current.on_event = emit
                    current.requested_skill = request.skill
                    current.prompt_version_id = prompt['id']
                    current.investigation_effort = request.effort

                    def checkpoint():
                        if stop.is_set():
                            raise Cancelled()
                        turn.checkpoint()

                    current.checkpoint = checkpoint
                    current.steering_messages = followups
                    current.request_offset = turn.model_requests
                    current.action_offset = turn.actions
                    current.turn_started = turn.started
                    current.model_requests = turn.model_requests
                    try:
                        current.checkpoint()
                        result = execute(
                            dataset_id,
                            request.model_copy(update={'message': message}),
                            current,
                            cfg,
                            session_id,
                            merged_attachments,
                            previous,
                            stop,
                            turn,
                            user_messages if followups else (),
                        )
                        lock.release()
                        released = True
                        trace_status = 'success'
                        trace.finish('success', result)
                        trace = None
                        emit('done', result)
                        break
                    except turn_control.Steered:
                        turn.model_requests = max(
                            turn.model_requests,
                            getattr(current, 'model_requests', 0),
                            getattr(current, 'memory_model_requests', 0),
                        )
                        turn.actions = max(turn.actions, getattr(current, 'actions_taken', 0))
                        continue
            except Cancelled:
                pass
            except Exception as exc:
                trace_status, trace_error = 'error', str(exc)
                if not stop.is_set():
                    message = (
                        str(exc)
                        if isinstance(exc, (provider.ModelError, index.RetrievalError, ValueError))
                        else 'The response could not be completed. Retry your question.'
                    )
                    emit('error', {'message': message[:500], 'run_id': trace.id if trace else None})
            finally:
                if trace:
                    trace.finish(trace_status, result, trace_error)
                turn_control.remove(request_id)
                if not released:
                    lock.release()
                if not stop.is_set():
                    output.put(None)

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
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


class SteeringRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    attachments: list[str] = Field(default_factory=list, max_length=8)


@router.post('/chat/{request_id}/steer')
def steer(dataset_id: str, request_id: str, body: SteeringRequest):
    check(dataset_id)
    guardrails.validate(body.message, dataset_id)
    if not body.message.strip():
        raise HTTPException(422, 'Type a message first.')
    turn = turn_control.find(request_id, dataset_id)
    for key in body.attachments:
        if not store.issue(dataset_id, key):
            raise HTTPException(422, 'An attached ticket is outside this import.')
    return turn.add({'id': body.id, 'message': body.message.strip(), 'attachments': body.attachments})


class ProjectContextRequest(BaseModel):
    content: str = Field(default='', max_length=12000)
    base_version_id: str | None = Field(default=None, max_length=100)


@router.get('/project-context')
def get_project_context(dataset_id: str, project: str = Query(default='', max_length=100)):
    check(dataset_id, project)
    return project_context.read(dataset_id, project)


@router.put('/project-context')
def save_project_context(
    dataset_id: str, request: ProjectContextRequest, project: str = Query(default='', max_length=100)
):
    check(dataset_id, project)
    return project_context.write(dataset_id, project, request.content, request.base_version_id)
