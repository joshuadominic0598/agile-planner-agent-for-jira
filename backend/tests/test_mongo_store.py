"""Real MongoDB queries, narrative-only retrieval and legacy migration integrity."""

import json
import sqlite3

from app import importer, store, vector_store
from app.agent import index
from app.agent.tools import Context
from app.main import app
from app.paths import ROOT, data_dir
from fastapi.testclient import TestClient

CSV = b'Issue key,Summary,Issue Type,Status,Status Category,Assignee,Sprint,Description,Score.$,Score.$\nAPP-1,Access controls,Story,Review,In Progress,Joshua Doe,Sprint 1,Secure login,2,4\nAPP-2,Release,Task,Production,Done,Jo Ann,Sprint 1,Ship login,,\n'


def test_native_mongo_person_filters_and_arbitrary_fields_without_csv_or_vectors(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    with TestClient(app) as client:
        dataset = client.post('/api/imports', files={'file': ('source.csv', CSV)}).json()['id']
        assert store.mongo().issues.count_documents({'dataset_id': dataset}) == 2
        context = Context(dataset)
        monkeypatch.setattr(
            importer,
            'parse_csv',
            lambda *args: (_ for _ in ()).throw(AssertionError('CSV queried after import')),
        )
        monkeypatch.setattr(
            index,
            'hybrid_search',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Metadata sent to vectors')),
        )
        assert context.find_people('joshua')['people'][0]['name'] == 'Joshua Doe'
        result = context.call(
            'query_metadata',
            {
                'filters': [{'field': 'assignee', 'operator': 'contains', 'value': 'joshua'}],
                'group_by': 'Score.$',
            },
        )
        assert result['total'] == 1 and result['storage'] == 'mongodb'
        assert {row['name'] for row in result['groups']} == {'2', '4'}
        assert client.get(f'/api/datasets/{dataset}/issues/APP-1').json()['fields']['Score.$'] == ['2', '4']
        literal = context.call(
            'query_metadata', {'filters': [{'field': 'assignee', 'operator': 'contains', 'value': '.*'}]}
        )
        assert literal['total'] == 0
        store.mongo().issues.update_one(
            {'dataset_id': dataset, 'key': 'APP-1'}, {'$set': {'summary.assignee': 'Taylor'}}
        )
        refreshed = context.call(
            'query_metadata', {'filters': [{'field': 'assignee', 'operator': 'eq', 'value': 'Joshua Doe'}]}
        )
        assert refreshed['total'] == 0
        assert index.status(dataset)['status'] == 'ready'
        with vector_store.connect() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'issues' not in tables and 'agent_messages' not in tables
        assert 'agent_chunks' in tables and 'agent_edges' in tables


def test_legacy_migration_preserves_ids_fields_memory_vectors_and_does_not_reapply(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    parsed, metadata = importer.parse_csv(CSV)
    source = sqlite3.connect(tmp_path / 'legacy.sqlite3')
    source.executescript("""
        CREATE TABLE datasets(id TEXT PRIMARY KEY,filename TEXT,imported_at TEXT,status TEXT,progress INT,message TEXT,metadata TEXT);
        CREATE TABLE issues(dataset_id TEXT,key TEXT,project TEXT,summary TEXT,details TEXT);
        CREATE TABLE agent_sessions(id TEXT,dataset_id TEXT,project TEXT,created_at TEXT);
        CREATE TABLE agent_messages(id INT,session_id TEXT,role TEXT,payload TEXT,created_at TEXT);
        CREATE TABLE agent_session_memory(session_id TEXT,dataset_id TEXT,state TEXT,updated_at TEXT);
        CREATE TABLE agent_project_context(dataset_id TEXT,project TEXT,content TEXT,updated_at TEXT);
    """)
    source.execute(
        'INSERT INTO datasets VALUES(?,?,?,?,?,?,?)',
        ('same-import', 'old.csv', 'today', 'ready', 100, 'ready', json.dumps(metadata)),
    )
    source.executemany(
        'INSERT INTO issues VALUES(?,?,?,?,?)',
        [
            ('same-import', summary['key'], 'APP', json.dumps(summary), json.dumps(details))
            for summary, details in parsed
        ],
    )
    source.execute('INSERT INTO agent_sessions VALUES(?,?,?,?)', ('same-chat', 'same-import', 'APP', 'today'))
    source.execute(
        'INSERT INTO agent_messages VALUES(?,?,?,?,?)',
        (17, 'same-chat', 'user', json.dumps({'content': 'Prior question'}), 'today'),
    )
    source.execute(
        'INSERT INTO agent_session_memory VALUES(?,?,?,?)',
        ('same-chat', 'same-import', json.dumps({'person': {'name': 'Joshua Doe'}}), 'today'),
    )
    source.execute(
        'INSERT INTO agent_project_context VALUES(?,?,?,?)', ('same-import', 'APP', 'Saved goals', 'today')
    )
    index.initialize(source)
    source.execute(
        'INSERT INTO agent_nodes VALUES(?,?,?,?,?,?)',
        ('same-import', 'APP-1', 'issue', 'Access controls', 'APP', 'APP-1'),
    )
    source.commit()
    source.close()
    store.initialize()
    assert store.dataset('same-import')['metadata'] == metadata
    assert store.issue('same-import', 'APP-1')['details']['fields']['Score.$'] == ['2', '4']
    assert store.mongo().agent_messages.find_one({'id': 17})['payload']['content'] == 'Prior question'
    assert (
        store.mongo().agent_session_memory.find_one({'session_id': 'same-chat'})['state']['person']['name']
        == 'Joshua Doe'
    )
    assert store.mongo().counters.find_one({'_id': 'message_id'})['value'] == 17
    with vector_store.connect() as db:
        assert (
            db.execute('SELECT label FROM agent_nodes WHERE issue_key=?', ('APP-1',)).fetchone()[0]
            == 'Access controls'
        )
    store.mongo().agent_project_context.update_one(
        {'dataset_id': 'same-import'}, {'$set': {'content': 'New goals'}}
    )
    store.initialize()
    assert store.mongo().issues.count_documents({}) == 2
    assert (
        store.mongo().agent_project_context.find_one({'dataset_id': 'same-import'})['content'] == 'New goals'
    )
    assert (tmp_path / 'legacy.sqlite3').exists()


def test_relative_data_path_is_anchored_to_project_not_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('JIRA_DATA_DIR', 'resources/tests/path-check')
    assert data_dir() == ROOT / 'resources/tests/path-check'
    assert not (tmp_path / 'resources').exists()


def test_oversized_ticket_fails_before_any_issue_is_written(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    content = (
        b'Issue key,Summary,Issue Type,Status,Description\nAPP-1,Large narrative,Story,To Do,'
        + b'x' * (6 * 1024 * 1024)
        + b'\n'
    )
    with TestClient(app) as client:
        dataset = client.post(
            '/api/imports', files={'file': ('large.csv', content)}, data={'prepare_agent': 'false'}
        ).json()['id']
        result = client.get(f'/api/imports/{dataset}').json()
        assert result['status'] == 'failed' and '16 MB' in result['message']
        assert store.mongo().issues.count_documents({'dataset_id': dataset}) == 0


def test_mongo_outage_has_clear_unavailable_message_and_no_csv_fallback(tmp_path, monkeypatch):
    from pymongo.errors import ServerSelectionTimeoutError

    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:

        def unavailable():
            raise ServerSelectionTimeoutError('private connection detail')

        monkeypatch.setattr(store, 'mongo', unavailable)
        result = client.get('/api/health')
        assert result.status_code == 503
        assert 'MongoDB is unavailable' in result.json()['detail']
        assert 'private connection detail' not in result.text
