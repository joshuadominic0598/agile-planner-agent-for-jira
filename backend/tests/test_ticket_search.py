"""Overview search stays metadata-exact for identifiers and ranks narratives transparently."""

import csv
import io

import pytest
from app import store
from app.agent import index
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def search_client(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    rows = [
        [
            'APP-1231',
            '77777',
            'NUCC taxonomy mappings',
            'Story',
            'In Progress',
            'In Progress',
            'APP',
            'Map specialist classifications',
            'High',
            'Ana',
            'Lee',
            'Sprint 2',
        ],
        [
            'APP-20',
            '20',
            'NUCC taxonomy',
            'Task',
            'Done',
            'Done',
            'APP',
            'Publish names',
            'Medium',
            'Bo',
            'Lee',
            'Sprint 1',
        ],
        [
            'APP-30',
            '30',
            'Validate imports',
            'Bug',
            'Awaiting audit',
            'In Progress',
            'APP',
            'Check NUCC taxonomy after importing; mentions ticket 999999',
            'High',
            'Ana',
            'Rae',
            'Sprint 2',
        ],
        [
            'APP-40',
            '40',
            'Provider classification',
            'Task',
            'To Do',
            'To Do',
            'APP',
            'Specialist ontology and categorization',
            'Urgent',
            'Bo',
            'Rae',
            'Sprint 2',
        ],
        [
            'OTHER-1231',
            '88888',
            'Unrelated login',
            'Bug',
            'In Progress',
            'In Progress',
            'OTHER',
            'Fix sign in',
            'Medium',
            'Cy',
            'Cy',
            'Other 1',
        ],
    ]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            'Issue key',
            'Issue id',
            'Summary',
            'Issue Type',
            'Status',
            'Status Category',
            'Project key',
            'Description',
            'Priority',
            'Assignee',
            'Reporter',
            'Sprint',
        ]
    )
    writer.writerows(rows)
    with TestClient(app) as client:
        data = client.post('/api/imports', files={'file': ('search.csv', out.getvalue().encode())}).json()
        yield client, data['id']


def get(search_client, **params):
    client, ident = search_client
    response = client.get(f'/api/datasets/{ident}/ticket-search', params=params)
    assert response.status_code == 200, response.text
    return response.json()


def keys(result):
    return [item['ticket']['key'] for item in result['items']]


@pytest.mark.parametrize(
    'query', ['1231', 'ticket 1231', 'app 1231', 'APP-1231', 'issue #1231', '#1231', '77777']
)
def test_number_forms_are_exact_metadata_only(search_client, monkeypatch, query):
    monkeypatch.setattr(
        index, 'status', lambda *_: pytest.fail('Identifier lookup must not query the vector store')
    )
    result = get(search_client, q=query, project='APP', semantic=True)
    assert keys(result) == ['APP-1231']
    assert result['mode'] == 'identifier'
    assert not result['can_expand']
    assert keys(get(search_client, q='ticket 999999')) == []


def test_shared_number_is_disambiguated_by_project_not_guessed(search_client):
    result = get(search_client, q='1231')
    assert set(keys(result)) == {'APP-1231', 'OTHER-1231'}
    assert result['total'] == 2 and 'Several' in result['notice']
    assert keys(get(search_client, q='other 1231')) == ['OTHER-1231']
    assert keys(get(search_client, q='other 1231', project='APP')) == []


def test_title_matches_precede_description_matches(search_client):
    result = get(search_client, q='nucc taxonomy', project='APP')
    assert keys(result) == ['APP-20', 'APP-1231', 'APP-30']
    assert [item['match'] for item in result['items']] == ['Title match', 'Title match', 'Description match']
    assert result['keyword_matches'] == 3
    assert result['total'] is None
    assert result['can_expand']


@pytest.mark.parametrize(
    'query,expected',
    [
        ('in progress', {'APP-1231', 'OTHER-1231'}),
        ('tickets in progress', {'APP-1231', 'OTHER-1231'}),
        ('high priority', {'APP-1231', 'APP-30'}),
        ('high priority bugs', {'APP-30'}),
        ('Awaiting audit', {'APP-30'}),
        ('priority: Urgent', {'APP-40'}),
        ('ticket 1231 high priority', {'APP-1231'}),
    ],
)
def test_basic_metadata_phrases_use_discovered_values(search_client, query, expected):
    result = get(search_client, q=query)
    assert set(keys(result)) == expected
    assert result['applied_filters']
    assert not result['can_expand']


def test_eight_filters_intersect_and_conflicting_query_filters_do_not_broaden(search_client):
    result = get(
        search_client,
        project='APP',
        status='Awaiting audit',
        category='In Progress',
        issue_type='Bug',
        priority='High',
        assignee='Ana',
        reporter='Rae',
        sprint='Sprint 2',
    )
    assert keys(result) == ['APP-30']
    assert len(result['applied_filters']) == 8
    assert keys(get(search_client, q='high priority', priority='Medium')) == []
    assert keys(get(search_client, assignee='.*')) == []


def test_hybrid_adds_semantic_candidates_after_titles_and_honors_metadata_scope(search_client, monkeypatch):
    called = []
    original_status = index.status

    def status(ident):
        state = original_status(ident)
        state['metadata']['embedding_provider'] = 'compatible'
        return state

    def hybrid(ident, query, **kwargs):
        called.append(kwargs)
        return [
            {'key': 'APP-40', 'excerpt': 'Specialist ontology', 'rerank_score': 1},
            {'key': 'OTHER-1231', 'excerpt': 'Outside filters', 'rerank_score': 2},
        ]

    monkeypatch.setattr(index, 'status', status)
    monkeypatch.setattr(index, 'hybrid_search', hybrid)
    lexical = get(search_client, q='nucc taxonomy', project='APP')
    assert not called and 'APP-40' not in keys(lexical)
    combined = get(search_client, q='nucc taxonomy', project='APP', semantic=True)
    assert keys(combined) == ['APP-20', 'APP-1231', 'APP-30', 'APP-40']
    assert combined['items'][-1]['match'] == 'Semantic match'
    assert 'OTHER-1231' not in called[0]['issue_keys']
    assert combined['items'][-1]['excerpt'] == 'Specialist ontology and categorization'


def test_missing_or_failed_semantics_retains_keyword_results(search_client, monkeypatch):
    monkeypatch.setattr(
        index,
        'hybrid_search',
        lambda *a, **k: (_ for _ in ()).throw(index.RetrievalError('Embedding unavailable')),
    )
    result = get(search_client, q='nucc taxonomy', semantic=True)
    assert len(result['items']) == 3 and 'unavailable' in result['notice']
    monkeypatch.setattr(index, 'status', lambda *_: {'status': 'missing', 'metadata': {}})
    result = get(search_client, q='nucc taxonomy', semantic=True)
    assert len(result['items']) == 3 and not result['can_expand']
    assert 'Prepare the ticket index' in result['notice']


def test_options_and_search_read_current_mongodb_metadata(search_client):
    client, ident = search_client
    options = client.get(f'/api/datasets/{ident}/ticket-search/options').json()['fields']
    assert len(options) == 8 and 'Awaiting audit' in options['status'] and 'Urgent' in options['priority']
    store.mongo().issues.update_one(
        {'dataset_id': ident, 'key': 'APP-40'}, {'$set': {'summary.summary': 'Fresh database title'}}
    )
    assert keys(get(search_client, q='Fresh database title')) == ['APP-40']
