# Startup and verification helpers

[Product tour](../README.md) · [Runtime commands](../docs/README.md#runtime-commands) · [Verification notes](../docs/README.md#verification)

Run commands below from the repository root.

| Script | Responsibility |
| --- | --- |
| `start.sh` | Check Docker, run Compose with a build/health wait, and open the browser |
| `verify_csv.py` | Compare a CSV against the running app using aggregate counts and field preservation |
| `verify_agent.py` | Check index contents, ticket/numeric lookup, project scope, totals and saved conversation behavior |
| `check-docs.py` | Check local Markdown links, heading anchors and portable image references |

## Validate documentation

```sh
make check-docs
```

Checks the README and linked guide folders for missing files, broken heading anchors, SVG image embeds and unrendered Mermaid blocks. Diagrams use PNG previews with separate editable sources. This check uses Python's standard library; external URLs are not fetched.

## Start

```sh
make start
```

Set `PORT` to change the host port or `OPEN_BROWSER=0` to skip browser launch. `make restart` reuses the existing image; `make start` includes a build using cached layers. Neither deletes the stored snapshots.

## Validate a CSV import

Requires the local Python dependencies and a running API. This helper uploads data unless `--check-id` is supplied.

```sh
PYTHONPATH=backend .venv/bin/python scripts/verify_csv.py /path/to/export.csv
PYTHONPATH=backend .venv/bin/python scripts/verify_csv.py /path/to/export.csv --check-id DATASET_ID
```

## Validate retrieval

Use the same source CSV and an existing dataset ID. The helper can build a missing agent index and writes test chat messages to that snapshot, so use a test import.

```sh
PYTHONPATH=backend .venv/bin/python scripts/verify_agent.py /path/to/export.csv --dataset DATASET_ID
```

This verifies retrieval behavior; it does not evaluate the semantic quality of every possible model answer.

## Verify migrated storage

With MongoDB running, compare all application documents and retrieval counts to the preserved migration source without displaying ticket text:

```sh
PYTHONPATH=backend .venv/bin/python scripts/verify_storage.py
```

Run immediately after migration; later edits intentionally differ from the archive. See [storage and migration](../docs/storage.md).

`start.sh` compares runtime source/dependency fingerprints and the local image ID. Unchanged `make start` calls reuse the image without contacting Docker Hub. Changed sources trigger a normal build; `make build` explicitly rebuilds. `image-fingerprint.sh` hashes only runtime inputs and never includes CSVs, credentials or stored data.

## Persistent workspace and a fresh start

`make restart` preserves MongoDB, uploaded source copies, profiles, conversations and the SQLite index. `make fresh-start` is the explicit reset: type `RESET`, stop the API, archive database/application records, then clear the active workspace and restart. The archive is private (`0600`) under `resources/app/backups/`. Original user exports and `.env` are not deleted. No reset runs automatically on refresh or startup.

`make monitor`, `make evaluation-dashboard` and `make dashboards` launch independent operations screens on ports 8012/8013. Their PID/log files stay under `resources/app/`. `make evaluation-setup`, `make evaluation-import` and `make evaluate RAGAS=1` prepare, import and replay the evaluation conversation. See the monitoring/evaluation guides in `docs/`.

`add-duplicate-fixture.py` is a deliberate test-data helper, never an import hook. It backs up the source CSV, preserves repeated column positions and adds one marked To Do duplicate with a different key/reporter. Do not use a modified fixture as an unmarked production export.
