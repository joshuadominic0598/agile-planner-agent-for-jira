"""Exercise the real MongoDB service using disposable, isolated test databases."""

import os
import uuid

import pytest
from pymongo import MongoClient


@pytest.fixture(autouse=True)
def isolated_mongo(monkeypatch, tmp_path):
    uri = os.environ.get('JIRA_TEST_MONGO_URI', 'mongodb://127.0.0.1:27018')
    name = 'sprintlens_test_' + uuid.uuid4().hex
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path / 'application'))
    monkeypatch.setenv('JIRA_MONGO_URI', uri)
    monkeypatch.setenv('JIRA_MONGO_DATABASE', name)
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    yield
    client.drop_database(name)
    client.close()


@pytest.fixture(autouse=True)
def isolate_scope_planner(monkeypatch):
    from app.agent import scope_planner

    # Answer-loop fixtures isolate retrieval; scope-planner tests restore the real stage explicitly.
    monkeypatch.setattr(scope_planner, 'rebuild', lambda *args: None)
