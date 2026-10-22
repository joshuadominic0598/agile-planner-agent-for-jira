# MongoDB storage and retrieval

[Technical guides](README.md) · [Agent retrieval](retrieval.md)

## Import once, query the database

The CSV parser runs only during upload. It preserves repeated headers and custom fields, normalizes core ticket metadata, resolves relationships, then writes MongoDB documents. The original CSV bytes are discarded. Dashboard and agent requests read MongoDB; they never reopen the CSV. The source hash and filename identify the imported snapshot.

`store.py` uses the official [PyMongo driver](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/), [collection bulk writes](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/bulk-write/) and [indexes](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/indexes/). Unique keys isolate records by snapshot and ticket. Compound metadata indexes cover project, assignee, reporter, status/category, priority, issue type, sprint and Jira issue ID.

Each `issues` document contains a normalized `summary`, complete `details` and `exported_fields` arrays. The array representation lets structured queries address custom column names containing periods or dollar signs without interpreting those names as MongoDB paths or operators. Repeated column values remain arrays. A normalized record exceeding MongoDB's 16 MB document limit produces an import error before any ticket is written.

## Agent query routing

- Assignees/reporters, status, sprint, priority, estimates, counts and custom fields use MongoDB. For “Joshua's tickets,” `find_people` resolves literal case-insensitive name matches and `query_metadata`/`employee_analysis` fetch actual assignments. Ambiguous people require clarification.
- `query_metadata` builds bounded, validated MongoDB filters and aggregation pipelines. Counts and grouped counts cover the complete matching collection, independently of pagination. User strings become escaped literal values; the model cannot submit raw MongoDB operators, JavaScript or SQL.
- Work topics use narrative vectors (title, description, acceptance criteria, comments and attachment references) and FTS5 keyword retrieval in `resources/app/retrieval.sqlite3`, with existing hybrid ranking, reranking and explicit graph links. Returned IDs are joined to current MongoDB ticket metadata. SQLite contains no issue source records, conversations or model settings.
- The connected model plans the investigation, selects tools and writes the streamed answer after reading evidence. No prebuilt report replaces it.

## Runtime and paths

`make start` runs the app and MongoDB 7. MongoDB is published only on `127.0.0.1:27018`; the app is on `127.0.0.1:8000`. These remain local single-user services. Database and configuration files bind to `resources/mongodb/` and `resources/mongodb-config/`; retrieval data and the credential encryption key bind to `resources/app/`. There are no active named data volumes.

For development, run `make database` before `make backend`. Host defaults are `JIRA_MONGO_URI=mongodb://127.0.0.1:27018` and `JIRA_MONGO_DATABASE=sprintlens`. Compose supplies `mongodb://mongodb:27017` internally. `MONGO_PORT` changes the published port; if changed, also set the host application's `JIRA_MONGO_URI`. An explicit remote URI is supported by host development; Compose uses its bundled database.

`JIRA_DATA_DIR` defaults to `resources/app` anchored to the repository, not the current shell directory. Tests use disposable `sprintlens_test_*` MongoDB databases; browser tests use `sprintlens_e2e` and `resources/tests/e2e`. Screenshot captures use temporary `sprintlens_screenshots_*` databases and `resources/screenshots/`, cleaned afterward. Test helpers do not use the production database.

## Existing workspace migration

A consistent backup of the former database is retained at `resources/app/legacy.sqlite3`. Startup copies imported issues and fields, workflow appearance, people profiles, model connections, project briefs, sessions/messages and memory into MongoDB with their existing IDs. Vector/FTS/graph tables are copied separately into `retrieval.sqlite3` so existing prepared indexes remain usable when embedding settings match.

The migration is restart-safe and upserts records until complete. MongoDB's `migrations` collection records source fingerprint and counts; completed migrations are skipped, so later edits are never overwritten by the archive. SQLite is not a runtime fallback if MongoDB is unavailable. Existing browser selections keep working because import/session IDs are retained. The original backup and the old Docker volume are retained for recovery; the old volume is no longer mounted.

An earlier Desktop `data` folder and old project `data` folder were moved intact to `resources/legacy/`. They contain previous development/test state and are not merged into the active production database.

## Backup and recovery

Stop the app and MongoDB with `make stop` before copying `resources/mongodb/`, `resources/mongodb-config/` and `resources/app/` together; copying a live database directory is not a consistent backup. Keep `.agent-secret-key` with encrypted connection records. For a live database, use MongoDB's backup tools. Stopping/rebuilding containers preserves bind-mounted files. Do not delete `resources/mongodb/` to restart the app.

MongoDB runs as one local standalone instance. Multi-record settings and chat writes are ordered operations, not replica-set transactions. Import readiness is published only after all validated ticket writes succeed; failed imports cannot be queried through the API. The server has one API worker and keeps its existing conversation locks. A database outage returns an unavailable message instead of silently consulting CSV or legacy SQLite.

## Verification

The migration passed 132 backend tests against real isolated MongoDB databases and all 48 desktop/mobile browser tests. [Recorded migration verification](verification/mongodb_migration.json) compares application documents to the preserved source and checks retrieval table counts. Four imports (2,139 tickets each), 126 chat messages and saved profiles/workflows/briefs were preserved; a live partial-assignee query matched MongoDB's direct count. The three previously prepared indexes remained ready, and persistence was checked after restarting MongoDB.

Docker Hub base-image lookup timed out during deployment. The verified existing runtime image was extended with the pinned PyMongo dependency and current app/frontend files using downloaded wheels. Normal unchanged `make start` now verifies the source fingerprint and image ID and reuses that image. Source changes still trigger the canonical Dockerfile build; `make build` explicitly rebuilds and requires registry access when base images are unavailable locally.
