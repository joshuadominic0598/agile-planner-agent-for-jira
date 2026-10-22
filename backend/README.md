# Backend and API

[Product tour](../README.md) · [Architecture and data contract](../docs/README.md) · [Agent internals](app/agent/README.md)

FastAPI imports CSV snapshots, persists tickets and metadata in MongoDB and serves project/sprint analytics, ticket details and configuration. In the container it also serves the built React app.

## Run locally

From the repository root, prepare dependencies once with `make setup`, then run:

```sh
make backend
```

Requires Python 3.12+. The API listens on `http://127.0.0.1:8000`; interactive OpenAPI documentation is at `/docs`. Run `make database` for MongoDB on localhost:27018. `JIRA_MONGO_URI` and `JIRA_MONGO_DATABASE` configure the connection. Retrieval data and the encryption key default to `resources/app/`, anchored to the project directory. See [local development](../docs/README.md#local-development) for the paired frontend process.

## Application modules

| Component | Responsibility |
| --- | --- |
| `backend/app/importer.py` | CSV validation, duplicate column preservation, normalization, import jobs |
| `backend/app/analytics.py` | Project/sprint totals and dynamically discovered status cards |
| `backend/app/workflow.py` | Exact status discovery, free-text renaming/merging, shared issue classifier |
| `backend/app/csv_schema.json` | Reference sample columns and repeated occurrences; not an allowlist |
| `backend/app/columns.py` | Core aliases, optional numeric fields, explicit units |
| `backend/app/fields.py` | Arbitrary field catalog, bounded value-count charts, exact filters |
| `backend/app/references.py` | Resolve ticket keys, IDs and project numbers to titles; preserve original CSV values |
| `backend/app/people.py` | Observed assignee/type distributions and validated developer/work-area profiles |
| `backend/app/hierarchy.py` | Parent key/ID and Epic Link resolution, child counts, cycle handling |
| `backend/app/agent/` | Persistent vector/keyword/graph retrieval, read-only tools, model adapters and scoped chat API |
| `backend/app/agent/skills/` | Evidence and response contracts for sprint/project/backlog/employee analysis |
| `backend/app/agent/project_context.py` / `capacity.py` | Owner-provided briefs and conditional capacity evidence |
| `backend/app/agent/conversation.py` | Persistent resolved people, ticket and metadata scope; prompt augmentation and contextual retrieval |
| `backend/app/agent/context_budget.py` | Model-aware history/evidence budgets and complete tool-round pruning |
| `backend/app/agent/topics.py` / `rerank.py` | Plain-data theme grouping and relevance/diversity policy |
| `backend/app/agent/ports.py` / `retrieval_cache.py` | Retrieval cache contract and injected, bounded TTL/LRU implementation |
| `backend/app/agent/grounding.py` | Ticket prefetch, single-ticket follow-ups, missed-tool retry and labeled retrieval fallback |
| `backend/app/agent/connections.py` | Encrypted server credentials, allowed model choices and redacted profile API |
| `backend/app/store.py` | MongoDB persistence, structured queries and restart recovery |
| `backend/app/main.py` | FastAPI endpoints and production static hosting |

## CSV compatibility

| Input | Contract |
| --- | --- |
| **Required columns** | Issue key, Summary, Status and Issue Type |
| **Recognized aliases** | Common alternatives such as Work item key, Title, Work Type and Workflow status; inspect `/api/csv-schema` for the full list |
| **Optional data** | Project, Sprint, Status Category, Priority, Assignee, Reporter, estimates, relationships and other exported fields enrich available views |
| **Extra/repeated columns** | Accepted and preserved; repeated headers retain all their values, and eligible fields support value-count charts |
| **Limits** | 30 MB, 50,000 issues and 1,000 named columns |
| **Invalid input** | Missing required fields, malformed rows and duplicate keys produce explanatory errors instead of silently dropping records |

Core header meanings must be recognized; rename unsupported localized headers to a supported alias. Unknown field semantics and units are not inferred. See the [data contract](../docs/data_and_roadmap.md) for compatibility and snapshot limits.

## HTTP API

Use [interactive OpenAPI documentation](http://localhost:8000/docs) while the app is running. Uploads run as background jobs; poll the returned import ID before requesting analytics.

```sh
curl -F 'file=@/path/to/export.csv' -F 'prepare_agent=true' \
  http://localhost:8000/api/imports

curl http://localhost:8000/api/imports/IMPORT_ID
curl http://localhost:8000/api/datasets/IMPORT_ID/projects
curl http://localhost:8000/api/datasets/IMPORT_ID/analytics
```

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/imports` | Multipart `file` and optional `prepare_agent`; returns an import ID with HTTP 202 |
| GET | `/api/imports/{id}` | Processing state, progress, errors, and import metadata |
| GET | `/api/datasets/{id}/projects` | Project names, keys, and counts |
| GET | `/api/datasets/{id}/analytics?project=KEY&sprint=NAME` | Overview and sprint metrics/distributions |
| GET | `/api/datasets/{id}/issues` | Project/sprint scope, `q`, `status`, `priority`, `issue_type`, `stage`, `category_id`, `resolution_id`, `relationship`, `field`, `field_value`, `field_missing`, `page`, `page_size` |
| GET | `/api/datasets/{id}/issues/{key}` | Normalized issue, original fields, direct parent and children across sprints |
| GET | `/api/csv-schema` | Recognized aliases, required core fields, reference sample occurrences |
| GET / PUT | `/api/datasets/{id}/workflow?project=KEY` | Discovered statuses and free-text names for one project |
| GET / PUT | `/api/datasets/{id}/workflows` | Multi-project status setup and validated configuration saves |
| GET | `/api/datasets/{id}/fields?project=KEY` | Field catalog, populated/distinct counts, chart eligibility |
| GET | `/api/datasets/{id}/field-analytics?field=NAME&project=KEY&sprint=NAME` | Scoped exact value counts, blanks, repeated-value overlap |
| GET / PUT | `/api/datasets/{id}/people` | Assignee/type metrics and saved per-project work-area/developer profiles |
| GET | `/api/health` | Service health |

Omit `project` for all projects or `sprint` for all issues. Use `sprint=__unscheduled__` for issues without a sprint. Issue pages default to 20 records; maximum is 100.

Agent routes are under `/api/datasets/{id}/agent`, including status, index preparation, sessions and streamed chat. See [agent API and execution notes](../docs/jira_agent.md) for request examples and provider settings.

## Checks

From the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
make check
```

`make check` also runs the selected frontend formatting checks. The [verification guide](../docs/README.md#verification) describes coverage and recorded results.

### Overview ticket search

The independent [ticket finder](../docs/ticket_search.md) supports exact number parsing, eight discovered metadata filters and progressive title/description keyword + hybrid search. `ticket_search.py` exposes `/api/datasets/{id}/ticket-search` and `/options`; the keyword pass works without a chat model or prepared vector index.

## Planning and inline analysis

See [Planning](../docs/planning.md) for `/planning/settings`, `/planning/report` and streamed `/analysis` contracts. The fictional [100-ticket export](../resources/demo/agileplanner-demo.csv) is served by `/api/demo.csv`.

Agent telemetry and evaluations live in `app/observability/`. The main API records chat and ticket/backlog analysis runs; the independent dashboard API reads these from MongoDB. Native Langfuse export is optional. See [monitoring](../docs/observability.md) and [evaluation](../docs/evaluation.md).

Potential duplicates use `app/duplicates.py`: only current To Do work is eligible, comparisons use normalized title/description plus indexed vectors, and cached results are tied to the persistent index version. `app/workspace_reset.py` performs the explicitly confirmed, archived reset; ordinary startup never clears data.

Evaluation datasets, immutable versions, CSV/DOCX/JSON imports, worker jobs and per-question reference/evidence metrics are served by the separate operations application. See [Evaluation](../docs/evaluation.md) for the API contract and validation rules. Runtime requirements include NLTK and rouge-score for deterministic overlap; Ragas and rapidfuzz remain in the isolated evaluation environment.
