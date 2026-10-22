"""Lossless handling of Jira's repeated CSV columns, with explicit validation."""
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

from . import columns, hierarchy, store

MAX_BYTES = 30 * 1024 * 1024
MAX_ROWS = 50_000
csv.field_size_limit(MAX_BYTES)
SCHEMA = json.loads(Path(__file__).with_name('csv_schema.json').read_text())
REFERENCE_COLUMNS = {columns.header_key(c) for c in SCHEMA['columns']}
ALIASES = columns.ALIASES


class ImportError(ValueError):
    pass


def parse_csv(content):
    if not content or len(content) > MAX_BYTES:
        raise ImportError("Upload a nonempty CSV up to 30 MB.")
    if b"\x00" in content:
        raise ImportError("The file contains binary data. Export a UTF-8 CSV from Jira.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportError("The file must be UTF-8 encoded. Re-export it as CSV UTF-8.")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = [h.strip() for h in next(reader)]
        if len(headers) > 1000 or any(not h for h in headers):
            raise ImportError("Use a CSV with named columns (up to 1,000 columns).")
        indexed = {}
        for i, header in enumerate(headers):
            indexed.setdefault(columns.header_key(header), []).append(i)
        mapped = {name: [i for alias in aliases for i in indexed.get(columns.header_key(alias), [])] for name, aliases in ALIASES.items()}
        if len(headers) == 1 and (';' in headers[0] or '\t' in headers[0]):
            raise ImportError('The CSV uses a semicolon or tab separator. Save it as comma-separated CSV UTF-8, then upload again.')
        missing = [name for name in ("key", "summary", "status", "type") if not mapped[name]]
        if missing:
            raise ImportError("Missing required Jira columns: " + ", ".join(missing) + ". Export all fields from Jira.")
        known = REFERENCE_COLUMNS | {columns.header_key(a) for aliases in ALIASES.values() for a in aliases}
        extra = list(dict.fromkeys(h for h in headers if columns.header_key(h) not in known))
        issues, keys, warnings = [], set(), []
        invalid_numbers = Counter()
        for number, row in enumerate(reader, start=2):
            if not row or not any(v.strip() for v in row):
                continue
            if len(issues) >= MAX_ROWS:
                raise ImportError("This version supports up to 50,000 issues per upload.")
            if len(row) != len(headers):
                raise ImportError(f"Row {number} has {len(row)} columns; expected {len(headers)}. Check CSV quoting.")
            def values(name):
                return list(dict.fromkeys(row[i].strip() for i in mapped[name] if row[i].strip()))
            def value(name, default=""):
                found = values(name)
                if len(found) > 1 and name != 'sprints':
                    raise ImportError(f"Row {number} has conflicting values for {name} in recognized columns. Keep one consistent value for this field.")
                return next(iter(found), default)
            key = value("key")
            if not key or any(not value(name) for name in ("summary", "status", "type")):
                raise ImportError(f"Row {number} has an empty key, summary, status, or issue type.")
            if key.casefold() in keys:
                raise ImportError(f"Duplicate issue key {key!r} at row {number}. Upload one record per issue.")
            keys.add(key.casefold())
            issue = {name: value(name) for name in ("key", "summary", "status", "type", "category", "priority", "assignee", "reporter", "created", "updated", "resolved")}
            issue.update(project_key=value("project_key", key.rsplit("-", 1)[0]), project_name=value("project_name", value("project_key", key.rsplit("-", 1)[0])), sprints=values("sprints"))
            # Every original column occurrence, including empty values, is retained.
            fields = {}
            for h, v in zip(headers, row):
                fields.setdefault(h, []).append(v)
            invalid_numbers.update(columns.enrich(issue, fields))
            # A resolution is a scalar Jira attribute; do not pick between conflicting values.
            for role in ('resolution', 'issue_id', 'parent_key', 'parent_id', 'parent_summary', 'epic_key'):
                value(role)
            issues.append((issue, {"description": value("description"), "fields": fields}))
    except (csv.Error, StopIteration) as exc:
        raise ImportError("The CSV is empty or malformed. Check delimiters and quoted values.") from exc
    if not issues:
        raise ImportError("The CSV contains a header but no issues.")
    hierarchy.decorate([issue for issue, _ in issues])
    cycle_count = sum(i.get('hierarchy_warning', '').startswith('Cyclic') for i, _ in issues)
    unresolved = sum(bool(i.get('parent_reference_problem')) for i, _ in issues)
    if unresolved:
        warnings.append(f'{unresolved} parent reference(s) could not be uniquely matched to an exported ticket. Titles are shown when available; missing or ambiguous references are labeled in details.')
    if cycle_count:
        warnings.append(f'{cycle_count} cyclic parent relationships excluded from hierarchy navigation; raw fields are preserved.')
    if not mapped["category"]:
        warnings.append("Status Category is missing. All status names are still shown exactly as discovered.")
    if not any(i[0]["sprints"] for i in issues):
        warnings.append("No sprint assignments found. Use All issues or Unscheduled to explore this export.")
    for role, count in invalid_numbers.items():
        label = 'story point values' if role == 'points' else f'{role.replace("_", " ")} values'
        warnings.append(f"{count} invalid {label} (or conflicting estimate columns) excluded from totals; original values retained in ticket details.")
    if extra:
        warnings.append(f"{len(extra)} additional column(s) preserved as exported fields. Their business meaning and units are not inferred; use Explore fields for value counts.")
    warnings.append("CSV snapshot: sprint activity and historical status transitions are unavailable. Choose a sprint explicitly; counts show status at export time.")
    metadata = {"issue_count": len(issues), "column_count": len(headers), "schema_version": 2, "extra_columns": extra, "recognized_fields": {role: list(dict.fromkeys(headers[i] for i in indices)) for role, indices in mapped.items() if indices}, "sha256": hashlib.sha256(content).hexdigest(), "repeated_columns": {k: n for k, n in Counter(headers).items() if n > 1}, "warnings": warnings}
    return issues, metadata


def process(dataset_id, content, prepare_agent=True):
    try:
        from .paths import data_dir
        uploads = data_dir() / "uploads"
        uploads.mkdir(exist_ok=True)
        source = uploads / (dataset_id + ".csv")
        source.write_bytes(content)
        source.chmod(0o600)
        store.update(dataset_id, "processing", 15, "Validating Jira columns and issue records")
        issues, metadata = parse_csv(content)
        store.update(dataset_id, "processing", 65, "Saving tickets and metadata to MongoDB")
        store.save_issues(dataset_id, issues)
        metadata['source_file'] = 'uploads/' + dataset_id + '.csv'
        store.update(dataset_id, 'ready', 100, 'Analytics ready', metadata)
        store.mongo().workspace_settings.update_one({'id':'workspace'}, {'$set':{'active_dataset':dataset_id}}, upsert=True)
    except (ImportError, store.RecordTooLarge) as exc:
        store.update(dataset_id, "failed", 0, str(exc))
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Import failed for dataset %s", dataset_id)
        store.update(dataset_id, "failed", 0, "Import failed unexpectedly. Please try again or inspect the server logs.")

    if prepare_agent and store.dataset(dataset_id)["status"] == "ready":
        from .agent import index
        if index.reserve(dataset_id):
            index.build(dataset_id)
