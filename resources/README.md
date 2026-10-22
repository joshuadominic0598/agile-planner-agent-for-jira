# Project resources

Public documentation assets and fictional examples live alongside ignored local runtime data:

| Folder | Contents |
| --- | --- |
| [images/](images/README.md) | Documentation screenshots and rendered diagrams; reusable technology icons and attribution live in `images/icons/` |
| [demo/](demo/) | Public fictional CSV exports and evaluation examples |
| `mongodb/` | MongoDB database files for tickets, original fields, imports, people, workflows, project briefs and conversations |
| `mongodb-config/` | MongoDB configuration files; explicitly bound to prevent an anonymous Docker volume |
| `app/` | `retrieval.sqlite3` (vector/keyword/graph index), encryption key and optional preserved `legacy.sqlite3` migration source |
| `legacy/` | Preserved folders from earlier development/test runs, including the former Desktop `data` directory |
| `tests/` | Isolated backend/browser verification files |
| `screenshots/` | Temporary synthetic screenshot workspaces |

`images/` and `demo/` are public project assets. Documentation assets use lowercase snake_case names, with `README.md` kept as the conventional entry point. Editable diagrams remain under `docs/diagrams/`.

Git ignores every other folder here by default. Only the resources guide, public images and four named fictional demo files are allowed; new runtime folders remain private automatically. See [what to commit](../docs/repository_setup.md) before adding new public assets or fixtures.

Private runtime folders are ignored by Git and excluded from Docker build contexts. `make start` creates the required folders and starts MongoDB plus the app. Stop with `make stop`; files remain. See [storage and migration](../docs/storage.md) for backup, MongoDB connection and migration details.

Uploaded source copies are kept under `resources/app/uploads/` and queried through MongoDB after import. The SQLite retrieval index under `resources/app/` is reused across conversations and refreshes. Reset archives stay in `resources/app/backups/`; deliberate fixture backups are in `resources/backups/`. Both are private and excluded from Git.

`resources/evaluation/` contains private conversation extraction, evaluation JSONL and run/setup logs. Metrics, evidence and human reviews live in MongoDB. Only fictional demo exports are committed.

The public `demo/agileplanner-evaluation.json` contains the 10-exchange golden conversation and canonical source evidence for `agileplanner-demo.csv`. `demo/evaluation-template.csv` demonstrates separate expected answers/evidence and candidate responses/retrieval. Private golden-set revisions and job results live in MongoDB; uploaded documents and private worker logs remain under project resources.
