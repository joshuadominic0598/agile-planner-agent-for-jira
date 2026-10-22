"""Read-only monitoring shell plus explicit feedback/evaluation review APIs on localhost."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from ..paths import ROOT
from .evaluation import router as evaluation_router
from .evaluation_datasets import router as datasets_router
from .evaluation_jobs import router as jobs_router
from .feedback import router as feedback_router
from .prompts import router as prompts_router
from .routes import router

app = FastAPI(title='AgilePlanner operations')
app.include_router(router)
app.include_router(feedback_router)
app.include_router(evaluation_router)
app.include_router(datasets_router)
app.include_router(jobs_router)
app.include_router(prompts_router)


@app.exception_handler(PyMongoError)
async def database_error(request, exc):
    return JSONResponse(
        status_code=503, content={'detail': 'MongoDB is unavailable. Start the workspace with make start.'}
    )


@app.get('/api/health')
def health():
    from .. import store

    store.mongo().command('ping')
    return {'status': 'ok'}


static = Path(os.environ.get('JIRA_STATIC_DIR', str(ROOT / 'frontend/dist')))
if static.is_dir():
    app.mount('/assets', StaticFiles(directory=static / 'assets'), name='assets')


@app.get('/{path:path}', include_in_schema=False)
def shell(path: str):
    if path.startswith('api/'):
        raise HTTPException(404, 'Operations route not found.')
    target = static / 'operations.html'
    if not target.is_file():
        raise HTTPException(503, 'Build the frontend with make test or pnpm --dir frontend build first.')
    return FileResponse(target)
