"""Verify a migrated workspace against its preserved SQLite source without printing ticket text."""

import json
import sqlite3

from app import store, vector_store
from app.paths import data_dir

source = sqlite3.connect(f'file:{data_dir() / "legacy.sqlite3"}?mode=ro', uri=True)
source.row_factory = sqlite3.Row
counts = {}
for table, keys, json_fields in [
    ('datasets', ['id'], ['metadata']), ('issues', ['dataset_id', 'key'], ['summary', 'details']),
    ('people', ['dataset_id', 'project', 'assignee'], ['profile']), ('workflows', ['dataset_id', 'project'], ['config']),
    ('agent_connections', ['id'], ['config']), ('agent_project_context', ['dataset_id', 'project'], []),
    ('agent_sessions', ['id'], []), ('agent_messages', ['id'], ['payload']), ('agent_session_memory', ['session_id'], ['state']),
]:
    count = 0
    for row in source.execute('SELECT * FROM ' + table):
        expected = dict(row)
        for field in json_fields:
            expected[field] = json.loads(expected[field])
        if table == 'issues':
            expected = store.issue_document(expected['dataset_id'], expected['summary'], expected['details'])
        actual = store.mongo()[table].find_one({key: expected[key] for key in keys}, {'_id': 0})
        assert actual == expected, f'Migration mismatch in {table}'
        count += 1
    counts[table] = count
with vector_store.connect() as db:
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tables.intersection({'issues', 'datasets', 'agent_messages', 'agent_connections'})
    for table in ['agent_indices', 'agent_chunks', 'agent_fts', 'agent_terms', 'agent_nodes', 'agent_edges']:
        expected = source.execute('SELECT count(*) FROM ' + table).fetchone()[0]
        actual = db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
        assert actual == expected, f'Retrieval count mismatch in {table}'
        counts[table] = actual
source.close()
print(json.dumps({'verified': True, 'metadata_store': 'mongodb', 'retrieval_store': 'sqlite', 'records': counts}, indent=2))
