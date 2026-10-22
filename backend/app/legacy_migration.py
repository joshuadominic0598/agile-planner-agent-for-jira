"""One-time, restart-safe conversion of preserved SQLite application records."""

import hashlib
import json
import sqlite3

from pymongo import ReplaceOne

from . import store, vector_store
from .paths import data_dir


def migrate():
    source = data_dir() / 'legacy.sqlite3'
    db = store.mongo()
    if not source.is_file() or db.migrations.find_one({'_id': 'sqlite-v1', 'complete': True}):
        return
    old = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
    old.row_factory = sqlite3.Row
    tables = {row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts = {}
    try:
        for table, identity, json_fields in [
            ('datasets', ['id'], ['metadata']),
            ('issues', ['dataset_id', 'key'], ['summary', 'details']),
            ('people', ['dataset_id', 'project', 'assignee'], ['profile']),
            ('workflows', ['dataset_id', 'project'], ['config']),
            ('agent_connections', ['id'], ['config']),
            ('agent_project_context', ['dataset_id', 'project'], []),
            ('agent_sessions', ['id'], []),
            ('agent_messages', ['id'], ['payload']),
            ('agent_session_memory', ['session_id'], ['state']),
        ]:
            if table not in tables:
                continue
            counts[table] = 0
            batch = []
            for row in old.execute('SELECT * FROM ' + table):
                item = dict(row)
                for field in json_fields:
                    item[field] = json.loads(item[field])
                if table == 'issues':
                    item = store.issue_document(item['dataset_id'], item['summary'], item['details'])
                batch.append(ReplaceOne({key: item[key] for key in identity}, item, upsert=True))
                counts[table] += 1
                if len(batch) == 500:
                    db[table].bulk_write(batch)
                    batch = []
            if batch:
                db[table].bulk_write(batch)
        with vector_store.connect() as target:
            for table in [
                'agent_indices',
                'agent_chunks',
                'agent_fts',
                'agent_terms',
                'agent_nodes',
                'agent_edges',
            ]:
                if table not in tables:
                    continue
                for (dataset_id,) in old.execute('SELECT DISTINCT dataset_id FROM ' + table):
                    target.execute('DELETE FROM ' + table + ' WHERE dataset_id=?', (dataset_id,))
                columns = [row[1] for row in old.execute('PRAGMA table_info(' + table + ')')]
                sql = (
                    'INSERT INTO '
                    + table
                    + '('
                    + ','.join(columns)
                    + ') VALUES('
                    + ','.join('?' for _ in columns)
                    + ')'
                )
                target.executemany(sql, old.execute('SELECT ' + ','.join(columns) + ' FROM ' + table))
            target.execute(
                "UPDATE agent_indices SET status='failed',message='Indexing interrupted by migration. Prepare the index again.' WHERE status='building'"
            )
        last = db.agent_messages.find_one({}, {'id': 1}, sort=[('id', -1)])
        db.counters.update_one(
            {'_id': 'message_id'}, {'$max': {'value': last['id'] if last else 0}}, upsert=True
        )
        with source.open('rb') as handle:
            fingerprint = hashlib.file_digest(handle, 'sha256').hexdigest()
        db.migrations.replace_one(
            {'_id': 'sqlite-v1'},
            {'_id': 'sqlite-v1', 'complete': True, 'counts': counts, 'source_sha256': fingerprint},
            upsert=True,
        )
    finally:
        old.close()
