import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from . import analytics, columns, fields, importer, people, references, store, workflow
from .agent.connections import router as connections_router
from .agent.routes import router as agent_router
from .agent.routes import workspace_router as conversation_router
from .analysis_routes import router as analysis_router
from .duplicates import router as duplicates_router
from .observability.feedback import router as feedback_router
from .paths import ROOT
from .ticket_search import router as ticket_search_router


@asynccontextmanager
async def lifespan(app):
    from .agent.retrieval_cache import MemoryRetrievalCache
    from .agent.skill_documents import load_skill_documents

    store.initialize()
    app.state.retrieval_cache = MemoryRetrievalCache()
    app.state.skill_catalog = load_skill_documents()
    try:
        yield
    finally:
        app.state.retrieval_cache.clear()


app = FastAPI(title='AgilePlanner API', version='0.1.0', lifespan=lifespan)

app.include_router(analysis_router)
app.include_router(ticket_search_router)
app.include_router(agent_router)
app.include_router(conversation_router)

app.include_router(connections_router)
app.include_router(duplicates_router)
app.include_router(feedback_router)


@app.exception_handler(PyMongoError)
async def storage_error(request, exc):
    return JSONResponse(
        status_code=503,
        content={'detail': 'MongoDB is unavailable. Start the database with make start, then retry.'},
    )


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, exc):
    # Pydantic's missing-field errors can echo an entire submitted body, including keys.
    if request.url.path.startswith('/api/agent/connections'):
        return JSONResponse(
            status_code=422,
            content={
                'detail': 'Check the connection name, provider, model and field types. API keys must be text.'
            },
        )
    return await request_validation_exception_handler(request, exc)


def ready(dataset_id):
    data = store.dataset(dataset_id)
    if not data:
        raise HTTPException(404, 'Import not found. Upload a Jira CSV to begin.')
    if data['status'] != 'ready':
        raise HTTPException(409, 'This import is not ready yet.')
    return data


@app.get('/api/workspace')
def workspace():
    if os.environ.get('JIRA_WORKSPACE_RESTORE', 'true').lower() == 'false':
        return {'dataset': None, 'persistent': True}
    active = store.mongo().workspace_settings.find_one({'id': 'workspace'}) or {}
    data = store.dataset(active.get('active_dataset')) if active.get('active_dataset') else None
    if not data:
        data = store.mongo().datasets.find_one({'status': 'ready'}, {'_id': 0}, sort=[('imported_at', -1)])
    return {'dataset': data, 'persistent': True, 'retrieval_store': 'sqlite'}


@app.get('/api/demo.csv')
def demo_csv():
    return FileResponse(
        ROOT / 'resources' / 'demo' / 'agileplanner-demo.csv',
        media_type='text/csv',
        filename='agileplanner-demo.csv',
    )


@app.get('/api/health')
def health():
    store.mongo().command('ping')
    return {'status': 'ok', 'metadata_store': 'mongodb', 'retrieval_store': 'sqlite'}


@app.post('/api/imports', status_code=202)
async def upload(
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    prepare_agent: Annotated[bool, Form()] = True,
    embedding_preset: Annotated[Literal['small', 'large', 'lexical'] | None, Form()] = None,
):
    try:
        if not file.filename or not file.filename.lower().endswith('.csv'):
            raise HTTPException(400, 'Choose a .csv export from Jira.')
        content = await file.read(importer.MAX_BYTES + 1)
        if not content or len(content) > importer.MAX_BYTES:
            raise HTTPException(413, 'Upload a nonempty CSV up to 30 MB.')
        if embedding_preset is not None:
            from .agent.config import embedding_config
            from .agent.embedding_profiles import apply_profile

            try:
                apply_profile(embedding_config(), embedding_preset)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        dataset_id = uuid.uuid4().hex
        store.create_dataset(
            dataset_id, Path(file.filename.replace('\\', '/')).name, datetime.now(timezone.utc).isoformat()
        )
        if embedding_preset is not None:
            store.mongo().datasets.update_one(
                {'id': dataset_id}, {'$set': {'embedding_preset': embedding_preset}}
            )
        background.add_task(importer.process, dataset_id, content, prepare_agent)
        return {'id': dataset_id, 'status': 'queued'}
    finally:
        await file.close()


@app.get('/api/imports/{dataset_id}')
def import_status(dataset_id: str):
    data = store.dataset(dataset_id)
    if not data:
        raise HTTPException(404, 'Import not found.')
    return data


@app.get('/api/datasets/{dataset_id}/projects')
def projects(dataset_id: str):
    ready(dataset_id)
    result = {}
    for i in store.summaries(dataset_id):
        p = result.setdefault(
            i['project_key'], {'key': i['project_key'], 'name': i['project_name'], 'count': 0}
        )
        p['count'] += 1
    return sorted(result.values(), key=lambda p: (-p['count'], p['key']))


def scoped(dataset_id, project):
    ready(dataset_id)
    issues = store.summaries(dataset_id, project)
    if project and not issues:
        raise HTTPException(404, 'Project not found in this import.')
    return issues


@app.get('/api/csv-schema')
def csv_schema():
    return {
        **importer.SCHEMA,
        'version': 2,
        'policy': 'Core columns plus arbitrary additional fields',
        'required': ['Issue key', 'Summary', 'Status', 'Issue Type'],
        'aliases': columns.ALIASES,
    }


@app.get('/api/datasets/{dataset_id}/workflow')
def get_workflow(dataset_id: str, project: str):
    if not project:
        raise HTTPException(400, 'Choose one project to configure its workflow.')
    rows = scoped(dataset_id, project)
    return workflow.describe(rows, store.workflows(dataset_id).get(project))


@app.put('/api/datasets/{dataset_id}/workflow')
def put_workflow(dataset_id: str, project: str, config: dict):
    if not project:
        raise HTTPException(400, 'Choose one project to configure its workflow.')
    rows = scoped(dataset_id, project)
    try:
        cleaned = workflow.validate(config, {i['status'] for i in rows})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    store.save_workflow(dataset_id, project, cleaned)
    return workflow.describe(rows, cleaned)


@app.get('/api/datasets/{dataset_id}/workflows')
def get_workflows(dataset_id: str, project: str | None = None):
    rows = scoped(dataset_id, project)
    configs = workflow.resolve(rows, store.workflows(dataset_id))
    counts = {}
    for issue in rows:
        p = counts.setdefault(
            issue['project_key'], {'key': issue['project_key'], 'name': issue['project_name'], 'count': 0}
        )
        p['count'] += 1
    return {
        'projects': [
            {**p, 'workflow': configs[p['key']]}
            for p in sorted(counts.values(), key=lambda p: (-p['count'], p['key']))
        ]
    }


@app.put('/api/datasets/{dataset_id}/workflows')
def put_workflows(dataset_id: str, config: dict):
    rows = scoped(dataset_id, None)
    available = {}
    for issue in rows:
        available.setdefault(issue['project_key'], set()).add(issue['status'])
    projects = config.get('projects')
    if not isinstance(projects, dict) or not projects or not set(projects) <= set(available):
        raise HTTPException(422, 'Choose existing projects and provide their status names.')
    cleaned = {}
    try:
        for key, value in projects.items():
            if not isinstance(value, dict):
                raise ValueError('Invalid project status mapping.')
            cleaned[key] = workflow.validate(value, available[key])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    store.save_workflows(dataset_id, cleaned)
    return {'saved_projects': list(cleaned)}


@app.get('/api/datasets/{dataset_id}/analytics')
def dashboard(dataset_id: str, project: str | None = None, sprint: str | None = None):
    issues = scoped(dataset_id, project)
    if sprint and sprint != '__unscheduled__' and not any(sprint in i['sprints'] for i in issues):
        raise HTTPException(404, 'Sprint not found in this project.')
    return analytics.dashboard(issues, sprint, workflow.resolve(issues, store.workflows(dataset_id)))


@app.get('/api/datasets/{dataset_id}/issues')
def issues(
    dataset_id: str,
    project: str | None = None,
    sprint: str | None = None,
    q: str = '',
    status: str = '',
    priority: str = '',
    resolution_id: str = '',
    issue_type: str = '',
    stage: str = '',
    category_id: str = '',
    field: str = '',
    field_value: str = '',
    field_missing: bool = False,
    relationship: str = '',
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    rows = scoped(dataset_id, project)
    configs = workflow.resolve(rows, store.workflows(dataset_id))
    if stage and stage not in {s['id'] for s in workflow.stage_counts([], configs)}:
        raise HTTPException(400, 'Workflow stage not found in this project view.')
    records = analytics.select(rows, sprint)
    if category_id:
        if category_id not in {c['id'] for c in analytics.category_counts(rows)}:
            raise HTTPException(400, 'Status category not found in this project view.')
        records = [i for i in records if workflow.stage_id('category:' + i['category']) == category_id]
    if stage:
        records = [i for i in records if workflow.group(i, configs)['id'] == stage]
    if resolution_id:
        if resolution_id not in {r['id'] for r in analytics.resolution_counts(rows)}:
            raise HTTPException(400, 'Resolution not found in this project view.')
        records = [
            i
            for i in records
            if workflow.stage_id('resolution:' + (i.get('resolution') or '')) == resolution_id
        ]
    if relationship:
        if relationship not in {'parents', 'children', 'standalone'}:
            raise HTTPException(400, 'Choose parents, children, or standalone.')
        records = [
            i
            for i in records
            if (
                i.get('is_parent')
                if relationship == 'parents'
                else i.get('has_parent')
                if relationship == 'children'
                else not i.get('is_parent') and not i.get('has_parent')
            )
        ]
    if field:
        raw = store.field_rows(dataset_id, project)
        if not any(field in r for r in raw.values()):
            raise HTTPException(400, 'Field not found in this export.')
        records = [i for i in records if fields.matches(raw[i['key']], field, field_value, field_missing)]
    needle = q.strip().casefold()
    records = [
        i
        for i in records
        if (not needle or needle in ' '.join((i['key'], i['summary'], i['assignee'])).casefold())
        and (not status or (i['status'] or 'Unspecified') == status)
        and (not priority or (i['priority'] or 'Unspecified') == priority)
        and (not issue_type or i['type'] == issue_type)
    ]
    records.sort(
        key=lambda i: (
            i['key'].rsplit('-', 1)[0],
            int(i['key'].rsplit('-', 1)[-1]) if i['key'].rsplit('-', 1)[-1].isdigit() else 0,
        ),
        reverse=True,
    )
    start = (page - 1) * page_size
    return {
        'items': records[start : start + page_size],
        'total': len(records),
        'page': page,
        'page_size': page_size,
    }


@app.get('/api/datasets/{dataset_id}/fields')
def field_catalog(dataset_id: str, project: str | None = None):
    scoped(dataset_id, project)
    return fields.catalog(store.field_rows(dataset_id, project))


@app.get('/api/datasets/{dataset_id}/field-analytics')
def field_analytics(dataset_id: str, field: str, project: str | None = None, sprint: str | None = None):
    records = scoped(dataset_id, project)
    raw = store.field_rows(dataset_id, project)
    if not any(field in record for record in raw.values()):
        raise HTTPException(400, 'Field not found in this export.')
    keys = {i['key'] for i in analytics.select(records, sprint)}
    try:
        selected = {key: record for key, record in raw.items() if key in keys}
        if not selected:
            return {'field': field, 'issues': 0, 'populated': 0, 'multiple_values': False, 'values': []}
        result = fields.breakdown(selected, field)
        index = references.Index(store.summaries(dataset_id))
        for value in result['values']:
            if value['missing']:
                continue
            contexts = {
                i['project_key']: i
                for i in records
                if i['key'] in selected and fields.matches(raw[i['key']], field, value['value'])
            }
            labels = set()
            for context in contexts.values():
                parts = references.display_fields({field: [value['value']]}, context, index)[field][0]
                labels.add(''.join(part['text'] for part in parts))
            value['label'] = ' / '.join(sorted(labels)) or value['value']
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get('/api/datasets/{dataset_id}/people')
def get_people(dataset_id: str, project: str | None = None, sprint: str | None = None):
    rows = scoped(dataset_id, project)
    return people.dashboard(rows, store.people_profiles(dataset_id), sprint)


@app.put('/api/datasets/{dataset_id}/people')
def put_people(dataset_id: str, config: dict):
    rows = scoped(dataset_id, None)
    try:
        cleaned = people.validate(config.get('people'), rows, store.people_profiles(dataset_id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    store.save_people(dataset_id, cleaned)
    return {'saved': len(cleaned)}


@app.get('/api/datasets/{dataset_id}/issues/{key}')
def issue(dataset_id: str, key: str):
    ready(dataset_id)
    row = store.issue(dataset_id, key)
    if not row:
        raise HTTPException(404, 'Issue not found in this import.')
    item = {**row['summary'], **row['details']}
    all_issues = store.summaries(dataset_id)
    item['display_fields'] = references.display_fields(item['fields'], item, references.Index(all_issues))
    item['children'] = [i for i in all_issues if i.get('parent_key') == key]
    item['parent'] = next((i for i in all_issues if i['key'] == item.get('parent_key')), None)
    return item


# Production: one origin serves the built React app and the API.
static = Path(os.environ.get('JIRA_STATIC_DIR', str(ROOT / 'frontend/dist')))
if not static.is_absolute():
    static = ROOT / static
if static.is_dir():
    app.mount('/assets', StaticFiles(directory=static / 'assets'), name='assets')

    @app.get('/{path:path}', include_in_schema=False)
    def frontend(path: str):
        if path == 'api' or path.startswith('api/'):
            raise HTTPException(404, 'API route not found.')
        return FileResponse(static / 'index.html')
