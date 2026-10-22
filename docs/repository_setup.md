# Preparing the repository

Commit the application and public examples so every checkout can create its own private workspace. The repository is named `agile-planner-agent-for-jira`; local startup uses paths relative to the checkout.

## What to commit

| Path | Shared contents |
| --- | --- |
| `backend/` | Python application, requirements files, schema, agent instructions and tests |
| `frontend/` | React source, public assets, tests, build configuration, `package.json` and `pnpm-lock.yaml` |
| `config/` | Optional Ollama model configuration recipes; no model weights |
| `scripts/` | Startup, verification, screenshot and maintenance helpers |
| `docs/` | Guides, editable diagrams and reviewed verification summaries |
| `resources/images/` | Published screenshots, diagram exports and attributed icons |
| `resources/demo/` | Only `README.md`, `agileplanner-demo.csv`, `agileplanner-evaluation.json` and `evaluation-template.csv`; all fictional |
| Root files | `README.md`, `Makefile`, `Dockerfile`, `compose.yaml`, `pyproject.toml`, `.gitignore`, `.dockerignore` and sanitized `.env.example` |
| `resources/README.md` | Public asset and private workspace layout |

Keep dependency lockfiles and requirements files: they describe what to install. Installed dependencies and build output are recreated by the setup commands.

## What stays on each computer

The [Git ignore rules](../.gitignore) exclude local configuration, credentials, user exports, databases, downloaded models, dependencies, caches and generated reports. The [Docker ignore rules](../.dockerignore) also keep these files out of the build context.

| Local path or state | What it holds |
| --- | --- |
| `.env` and `.env.*` except `.env.example` | Personal provider settings, API credentials and local overrides |
| `jiratickets.csv` and other user CSV/document exports | Private source tickets and attachments; the two explicitly allowed demo CSVs are fictional |
| `resources/app/` | Uploaded exports, retrieval vectors, encryption key, dashboard logs and reset backups |
| `resources/mongodb/`, `resources/mongodb-config/` | Imported tickets, people, workflow settings, model profiles, prompts, conversations, monitoring and evaluation records |
| Other `resources/` folders | Local backups, migrations, evaluation imports/results, test workspaces, temporary screenshots, reference materials and build caches |
| `.venv/`, `.venv-*/`, `node_modules/`, `.pnpm-store/` | Installed dependencies and package caches |
| `frontend/dist/`, test reports, coverage and logs | Generated output |
| Ollama's model storage, normally outside this checkout | Downloaded chat/embedding weights; each user installs their own |
| Browser storage | Local display preferences and selections; stored by the browser, outside Git |

New folders under `resources/` are ignored by default. Only the public images, the resources guide and the four named demo files are allowed. Put new private JSON files, conversations, exports and attachments in the local resource folders, rather than alongside source code. Add new public fixtures through a deliberate `.gitignore` exception after reviewing their contents.

## Review the first commit

If this folder has no Git repository yet, initialize it when ready:

```sh
git init -b main
git status --short
git add --dry-run .
```

The dry run lists eligible files without staging them. Review that list, then stage and inspect the exact changes:

```sh
git add .
git diff --cached --stat
git diff --cached
```

Use `git status --short --ignored` to inspect excluded paths, or `git check-ignore -v jiratickets.csv .env resources/app/retrieval.sqlite3` to see the rules protecting specific files. Ignore rules do not remove files already tracked by Git; if a private file was previously committed, remove it from tracking and address its history and any exposed credentials before sharing.

## What another user needs

1. Clone [agile-planner-agent-for-jira](https://github.com/joshuadominic0598/agile-planner-agent-for-jira) and start Docker Desktop, or Docker Engine with Compose.
2. Run `make start` from the checkout. It builds the frontend/backend, starts MongoDB and creates that user's ignored workspace folders. No existing database, `.env` or private export is needed.
3. Open [localhost:8000](http://localhost:8000) and choose **Use demo export**, or upload their own Jira CSV. Their data stays in their checkout's local workspace.
4. For private AI, install Ollama, download a chat model and the chosen embedding model, then configure the local connection. See [private local AI setup](../README.md#private-local-ai-setup). Models, saved connections and API keys are not bundled in the repository.

The default Docker Desktop Ollama endpoint is `host.docker.internal`. On native Linux Docker Engine, configure host access to Ollama as described in the [model setup guide](jira_agent.md#connect-a-model-through-environment-variables) before enabling local AI.

Developers can run `make setup` for the Python and frontend dependencies; [local development](README.md#local-development) lists the prerequisites. Optional evaluation dependencies use `make evaluation-setup`.
