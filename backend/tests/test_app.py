import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import analytics, importer, store


HEADERS = ['Issue key', 'Summary', 'Issue Type', 'Status', 'Status Category', 'Project key', 'Project name', 'Priority', 'Assignee', 'Sprint', 'Sprint', 'Comment', 'Comment', 'Description', 'Custom field (Story point estimate)']
ROWS = [
    ['DEMO-1', 'Build checkout', 'Story', 'Done', 'Done', 'DEMO', 'Demo project', 'Medium', 'Ana', 'Sprint 9', 'Sprint 10', 'First note', 'Second note', 'A description\nwith a newline, and comma.', '5'],
    ['DEMO-2', 'Fix a bug', 'Bug', 'Testing', 'In Progress', 'DEMO', 'Demo project', 'High', '', 'Sprint 10', '', '', '', '<script>alert(1)</script>', '3'],
    ['DEMO-3', 'Release the app', 'Task', 'Production', 'Done', 'DEMO', 'Demo project', 'Highest', 'Ben', 'Sprint 10', '', '', '', '', ''],
    ['DEMO-4', 'Test complete', 'Task', 'Test Complete', 'In Progress', 'DEMO', 'Demo project', '', 'Ana', 'Sprint 10', 'Sprint 10', '', '', '', '0'],
    ['DEMO-5', 'Next up', 'Story', 'To Do', 'To Do', 'DEMO', 'Demo project', 'Low', '', '', '', '', '', '', 'NaN'],
    ['OTHER-1', 'Another project', 'Idea', 'To Do', 'To Do', 'OTHER', 'Other project', 'Low', 'Cam', 'Another board 1', '', '', '', '', ''],
]


def encode(rows=ROWS, headers=HEADERS):
    f = io.StringIO(newline='')
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(rows)
    return ('\ufeff' + f.getvalue()).encode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        yield client


def upload(client, content=None):
    response = client.post('/api/imports', files={'file': ('export.csv', content if content is not None else encode(), 'text/csv')})
    assert response.status_code == 202
    return response.json()['id']


def test_import_preserves_repeated_fields_and_snapshot_counts(client):
    dataset = upload(client)
    job = client.get(f'/api/imports/{dataset}').json()
    assert job['status'] == 'ready'
    assert job['metadata']['issue_count'] == 6
    assert job['metadata']['repeated_columns']['Sprint'] == 2
    assert any('invalid story point' in w for w in job['metadata']['warnings'])
    data = client.get(f'/api/datasets/{dataset}/analytics', params={'project': 'DEMO', 'sprint': 'Sprint 10'}).json()
    assert data['overall']['total'] == 5
    assert {g['label']: g['count'] for g in data['stages']} == {'Done': 1, 'Testing': 1, 'Production': 1, 'Test Complete': 1, 'To Do': 1}
    assert 'completed' not in data['overall']
    assert data['suggested_sprint'] == 'Sprint 10'
    assert data['sprint']['metrics']['total'] == 4
    assert sum(s['count'] for s in data['sprint']['stages']) == 4
    assert next(s for s in data['sprint']['stages'] if s['label'] == 'To Do')['count'] == 0
    assert data['sprint']['metrics']['story_points'] == 8
    assert data['sprint']['metrics']['estimated_issues'] == 3  # Zero is estimated
    detail = client.get(f'/api/datasets/{dataset}/issues/DEMO-1').json()
    assert detail['fields']['Comment'] == ['First note', 'Second note']
    assert detail['fields']['Sprint'] == ['Sprint 9', 'Sprint 10']
    assert detail['description'] == ROWS[0][13]
    assert detail['sprints'] == ['Sprint 9', 'Sprint 10']


def test_projects_filters_pagination_unscheduled_and_scope(client):
    dataset = upload(client)
    base = f'/api/datasets/{dataset}'
    projects = client.get(f'{base}/projects').json()
    assert [(p['key'], p['count']) for p in projects] == [('DEMO', 5), ('OTHER', 1)]
    response = client.get(f'{base}/issues', params={'project': 'DEMO', 'sprint': 'Sprint 10', 'q': 'BUG', 'priority': 'High', 'status': 'Testing', 'issue_type': 'Bug'}).json()
    assert [i['key'] for i in response['items']] == ['DEMO-2']
    first = client.get(f'{base}/issues', params={'project': 'DEMO', 'page_size': 2}).json()
    second = client.get(f'{base}/issues', params={'project': 'DEMO', 'page_size': 2, 'page': 2}).json()
    assert first['total'] == 5
    assert len({i['key'] for i in first['items'] + second['items']}) == 4
    assert client.get(f'{base}/issues', params={'sprint': '__unscheduled__'}).json()['total'] == 1
    assert client.get(f'{base}/issues', params={'priority': 'Unspecified'}).json()['total'] == 1
    assert client.get(f'{base}/analytics', params={'project': 'OTHER'}) .json()['overall']['total'] == 1
    assert client.get(f'{base}/issues', params={'page': 0}).status_code == 422
    assert client.get(f'{base}/issues', params={'page_size': 101}).status_code == 422
    assert client.get(f'{base}/analytics', params={'project': 'unknown'}).status_code == 404
    assert client.get(f'{base}/analytics', params={'project': 'OTHER', 'sprint': 'Sprint 10'}).status_code == 404
    assert client.get(f'{base}/issues/MISSING-1').status_code == 404
    assert client.get('/api/imports/missing').status_code == 404


@pytest.mark.parametrize('content,fragment', [
    (b'foo,bar\n1,2', 'Missing required'),
    (encode([ROWS[0], ROWS[0]]), 'Duplicate issue key'),
    (encode([ROWS[0][:-1]]), 'columns'),
    (encode([]), 'no issues'),
    (b'\xff\xfe\x80', 'UTF-8'),
    (b'\x00binary', 'binary'),
    (encode([[''] + ROWS[0][1:]]), 'empty key'),
])
def test_bad_import_fails_explicitly_without_partial_records(client, content, fragment):
    dataset = upload(client, content)
    job = client.get(f'/api/imports/{dataset}').json()
    assert job['status'] == 'failed'
    assert fragment in job['message']
    assert store.summaries(dataset) == []
    assert client.get(f'/api/datasets/{dataset}/analytics').status_code == 409


def test_upload_limits_and_filename_validation(client, monkeypatch):
    assert client.post('/api/imports', files={'file': ('file.txt', b'abc')}).status_code == 400
    assert client.post('/api/imports', files={'file': ('empty.csv', b'')}).status_code == 413
    monkeypatch.setattr(importer, 'MAX_BYTES', 10)
    assert client.post('/api/imports', files={'file': ('large.csv', b'12345678901')}).status_code == 413
    assert client.get('/api/health').json() == {'status': 'ok', 'metadata_store': 'mongodb', 'retrieval_store': 'sqlite'}


def test_fallback_statuses_no_sprint_and_mixed_sprint_names():
    content = b'Issue key,Summary,Issue Type,Status\nA-1,A,Task,Done\nA-2,B,Bug,In Progress\nA-3,C,Task,Deployed\n'
    issues, metadata = importer.parse_csv(content)
    result = analytics.dashboard([i for i, _ in issues])
    assert {g['label']: g['count'] for g in result['stages']} == {'Done': 1, 'In Progress': 1, 'Deployed': 1}
    assert result['sprints'] == []
    assert len(metadata['warnings']) == 3
    sorted(['9 sprint', 'Alpha 2', 'Alpha 10'], key=analytics.sprint_sort)


def test_snapshot_persists_and_restart_marks_interrupted_import(client):
    dataset = upload(client)
    store.create_dataset('unfinished', 'file.csv', 'today', status='processing')
    store.initialize()
    assert store.dataset(dataset)['status'] == 'ready'
    assert len(store.summaries(dataset)) == 6
    assert store.dataset('unfinished')['status'] == 'failed'


def test_imports_are_independent_and_failed_upload_keeps_previous_data(client):
    first = upload(client)
    second = upload(client, encode([ROWS[-1]]))
    failed = upload(client, b'bad,data\n1,2')
    assert store.dataset(failed)['status'] == 'failed'
    assert len(store.summaries(first)) == 6
    assert len(store.summaries(second)) == 1
    assert client.get(f'/api/datasets/{second}/issues/DEMO-1').status_code == 404


def test_limits_reject_without_truncating(monkeypatch):
    monkeypatch.setattr(importer, 'MAX_ROWS', 2)
    with pytest.raises(importer.ImportError, match='50,000'):
        importer.parse_csv(encode())


def test_schema_boundary_and_full_sample_header_preservation(client):
    headers = ['Issue key', 'Summary', 'Issue Type', 'Status', 'Totally new column']
    dataset = upload(client, encode([['A-1', 'A', 'Task', 'To Do', 'x']], headers))
    assert store.dataset(dataset)['status'] == 'ready'
    assert store.dataset(dataset)['metadata']['extra_columns'] == ['Totally new column']
    assert client.get(f'/api/datasets/{dataset}/issues/A-1').json()['fields']['Totally new column'] == ['x']
    schema = client.get('/api/csv-schema').json()
    assert 'Sprint' in schema['columns']
    assert 'Comment' in schema['columns']
    assert 'Custom field (QA Owner)' in schema['columns']
    # All 232 supported column occurrences, including repeated and empty values.
    columns = [name for name in schema['columns'] for _ in range(schema['sample_occurrences'][name])]
    assert len(columns) == 232
    row = [{'Issue key': 'A-1', 'Summary': 'A', 'Issue Type': 'Task', 'Status': 'To Do'}.get(c, '') for c in columns]
    data, _ = importer.parse_csv(encode([row], columns))
    assert sum(len(values) for values in data[0][1]['fields'].values()) == len(columns)


def test_free_text_names_merge_only_when_user_chooses_and_filter_exactly(client):
    dataset = upload(client)
    base = f'/api/datasets/{dataset}'
    config = client.get(base + '/workflow', params={'project': 'DEMO'}).json()
    assert config['assignments'] == {s: s for s in ['Done','Testing','Production','Test Complete','To Do']}
    assert not config['customized']
    config['assignments'].update({'Done': 'Delivered', 'Production': 'Delivered', 'Testing': 'Validation', 'Test Complete': 'Validation'})
    saved = client.put(base + '/workflow', params={'project': 'DEMO'}, json=config)
    assert saved.status_code == 200
    assert saved.json()['customized']
    assert {g['label'] for g in saved.json()['groups']} == {'Delivered', 'Validation', 'To Do'}
    for project in ['DEMO', 'OTHER', '']:
        for sprint in ['', 'Sprint 10'] if project != 'OTHER' else ['']:
            scope = {'project': project, 'sprint': sprint}
            data = client.get(base + '/analytics', params=scope).json()
            assert sum(s['count'] for s in data['sprint']['stages']) == data['sprint']['metrics']['total']
            for stage in data['sprint']['stages']:
                filtered = client.get(base + '/issues', params={**scope, 'stage': stage['id']}).json()
                assert filtered['total'] == stage['count']
    data = client.get(base + '/analytics', params={'project': 'DEMO', 'sprint': 'Sprint 10'}).json()
    assert {g['label']: g['count'] for g in data['sprint']['stages']} == {'Delivered': 2, 'Validation': 2, 'To Do': 0}
    validation = next(g for g in data['stages'] if g['label'] == 'Validation')['id']
    assert client.get(base + '/issues', params={'project': 'DEMO', 'stage': validation, 'q': 'bug', 'priority': 'High'}).json()['total'] == 1
    assert client.get(base + '/issues', params={'stage': 'missing'}).status_code == 400
    assert client.get(base + '/issues/DEMO-3').json()['status'] == 'Production'
    store.initialize()
    assert client.get(base + '/workflow', params={'project': 'DEMO'}).json()['assignments']['Production'] == 'Delivered'


@pytest.mark.parametrize('change', ['missing_status', 'unknown_status', 'empty', 'not_string', 'too_long'])
def test_invalid_names_cannot_replace_saved_mapping(client, change):
    dataset = upload(client)
    url = f'/api/datasets/{dataset}/workflow?project=DEMO'
    config = client.get(url).json()
    assert client.put(url, json=config).status_code == 200
    if change == 'missing_status':
        config['assignments'].pop('Done')
    elif change == 'unknown_status':
        config['assignments']['unknown'] = 'A stage'
    else:
        config['assignments']['Done'] = {'empty': '  ', 'not_string': None, 'too_long': 'x' * 121}[change]
    assert client.put(url, json=config).status_code == 422
    assert client.get(url).json()['assignments']['Done'] == 'Done'


def test_unknown_and_case_distinct_statuses_stay_visible_without_inference(client):
    headers = ['Issue key', 'Summary', 'Issue Type', 'Status', 'Status Category', 'Project key']
    statuses = ['Awaiting customer approval', 'Ready for validation', 'Done', 'DONE', 'Review / 安全'] + [f'Stage {i}' for i in range(40)]
    rows = [[f'A-{i}', 'A', 'Custom type', status, 'Done', 'A'] for i, status in enumerate(statuses)]
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}'
    config = client.get(base + '/workflow', params={'project': 'A'}).json()
    assert config['assignments'] == {status: status for status in statuses}
    assert len(config['groups']) == len(statuses)
    assert len(client.get(base + '/analytics').json()['stages']) == len(statuses)
    assert client.put(base + '/workflow', params={'project': 'A'}, json=config).status_code == 200


def test_onboarding_batch_saves_multiple_projects_atomically(client):
    dataset = upload(client)
    base = f'/api/datasets/{dataset}'
    setup = client.get(base + '/workflows').json()
    assert [p['key'] for p in setup['projects']] == ['DEMO', 'OTHER']
    configs = {p['key']: {'assignments': p['workflow']['assignments']} for p in setup['projects']}
    configs['DEMO']['assignments']['To Do'] = 'Planning'
    configs['OTHER']['assignments']['To Do'] = 'Planning'
    assert client.put(base + '/workflows', json={'projects': configs}).status_code == 200
    stages = client.get(base + '/analytics').json()['stages']
    planning = next(g for g in stages if g['label'] == 'Planning')
    assert planning['count'] == 2
    assert client.get(base + '/issues', params={'stage': planning['id']}).json()['total'] == 2
    assert client.get(base + '/issues', params={'project': 'OTHER', 'stage': planning['id']}).json()['total'] == 1
    configs['DEMO']['assignments']['Done'] = 'Changed'
    configs['OTHER']['assignments'] = {}
    assert client.put(base + '/workflows', json={'projects': configs}).status_code == 422
    assert client.get(base + '/workflow', params={'project': 'DEMO'}).json()['assignments']['Done'] == 'Done'
    assert client.put(base + '/workflows', json={'projects': {'unknown': {}}}).status_code == 422
    assert len(client.get(base + '/workflows', params={'project': 'DEMO'}).json()['projects']) == 1


def test_saved_legacy_labels_survive_without_fixed_bucket_roles(client):
    dataset = upload(client)
    config = {'groups': [{'id': 'old', 'label': 'My delivery stage', 'kind': 'completed'}], 'assignments': {s: 'old' for s in ['Done','Testing','Production','Test Complete','To Do']}}
    store.save_workflow(dataset, 'DEMO', config)
    value = client.get(f'/api/datasets/{dataset}/workflow', params={'project': 'DEMO'}).json()
    assert set(value['assignments'].values()) == {'My delivery stage'}
    assert all('kind' not in g for g in value['groups'])
    assert client.put(f'/api/datasets/{dataset}/workflow', params={'project': 'DEMO'}, json=value).status_code == 200
    assert store.workflows(dataset)['DEMO']['version'] == 3


def test_status_categories_are_source_values_and_independent_of_display_names(client):
    dataset = upload(client)
    base = f'/api/datasets/{dataset}'
    before = client.get(base + '/analytics', params={'project': 'DEMO', 'sprint': 'Sprint 10'}).json()
    assert {c['label']: c['count'] for c in before['categories']} == {'Done': 2, 'In Progress': 2, 'To Do': 1}
    assert {c['label']: c['count'] for c in before['sprint']['categories']} == {'Done': 2, 'In Progress': 2, 'To Do': 0}
    for category in before['sprint']['categories']:
        filtered = client.get(base + '/issues', params={'project': 'DEMO', 'sprint': 'Sprint 10', 'category_id': category['id']}).json()
        assert filtered['total'] == category['count']
    config = client.get(base + '/workflow', params={'project': 'DEMO'}).json()
    config['assignments'] = {status: 'Everything together' for status in config['assignments']}
    assert client.put(base + '/workflow', params={'project': 'DEMO'}, json=config).status_code == 200
    after = client.get(base + '/analytics', params={'project': 'DEMO', 'sprint': 'Sprint 10'}).json()
    assert after['categories'] == before['categories']
    assert after['sprint']['categories'] == before['sprint']['categories']
    assert len(after['stages']) == 1
    assert client.get(base + '/issues', params={'category_id': 'unknown'}).status_code == 400


def test_arbitrary_and_missing_category_names_are_not_reclassified(client):
    headers = ['Issue key','Summary','Issue Type','Status','Status Category']
    dataset = upload(client, encode([['A-1','A','Task','Production','Custom category'],['A-2','B','Task','Done','']], headers))
    base = f'/api/datasets/{dataset}'
    data = client.get(base + '/analytics').json()
    assert {c['label']: c['count'] for c in data['categories']} == {'Custom category': 1, 'Not provided': 1}
    missing = next(c['id'] for c in data['categories'] if c['label'] == 'Not provided')
    assert client.get(base + '/issues', params={'category_id': missing}).json()['items'][0]['key'] == 'A-2'


def test_aliases_estimates_and_resolution_remain_independent(client):
    headers = ['Work item key','Title','Work Type','Workflow status','Status Category','Story Points','Original estimate','Remaining Estimate','Time Spent','Resolution','Effort hours']
    rows = [['A-1','Feature','Story','Done','Done','5','7200','1800','3600','','99'], ['A-2','Defect','Bug','Review','In Progress','','0','','NaN','Duplicate','100']]
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}'
    assert store.dataset(dataset)['status'] == 'ready'
    data = client.get(base + '/analytics').json()
    metrics = data['overall']
    assert metrics['story_points'] == 5
    assert metrics['estimated_issues'] == 1
    assert metrics['original_hours'] == 2
    assert metrics['time_estimated_issues'] == 2  # Numeric zero is present.
    assert metrics['remaining_hours'] == .5
    assert metrics['spent_hours'] == 1
    assert metrics['spent_time_issues'] == 1
    assert metrics['resolution_set_issues'] == 1
    assert {c['label']: c['count'] for c in data['categories']} == {'Done': 1, 'In Progress': 1}
    for r in data['sprint']['resolutions']:
        assert client.get(base + '/issues', params={'resolution_id': r['id']}).json()['total'] == r['count']
    assert client.get(base + '/issues', params={'resolution_id': 'invalid'}).status_code == 400
    assert client.get(base + '/issues/A-1').json()['fields']['Effort hours'] == ['99']
    assert store.dataset(dataset)['metadata']['recognized_fields']['key'] == ['Work item key']


def test_conflicting_core_aliases_fail_and_ambiguous_estimates_are_excluded(client):
    headers = ['Issue key','Key','Summary','Status','Issue Type','Story Points','Custom field (Story point estimate)']
    dataset = upload(client, encode([['A-1','A-2','A','Done','Task','3','5']], headers))
    assert store.dataset(dataset)['status'] == 'failed'
    assert 'conflicting values for key' in store.dataset(dataset)['message']
    dataset = upload(client, encode([['A-1','A-1','A','Done','Task','3','5']], headers))
    assert store.dataset(dataset)['status'] == 'ready'
    data = client.get(f'/api/datasets/{dataset}/analytics').json()
    assert data['overall']['estimated_issues'] == 0
    assert any('conflicting estimate columns' in w for w in store.dataset(dataset)['metadata']['warnings'])


def test_custom_fields_repeated_values_blanks_scope_and_safe_charts(client):
    headers = ['Issue key','Summary','Status','Issue Type','Sprint','Team label','Team label','Long notes','Unique value']
    rows = [[f'A-{i}','A','Review','Custom type','Sprint 1' if i < 2 else 'Sprint 2','Alpha' if i == 0 else '', 'Alpha' if i == 0 else 'Beta' if i == 1 else '', 'x' * 121,str(i)] for i in range(51)]
    rows[1][5] = 'Alpha'
    rows.append(['B-1','B','Review','Task','Sprint 1','Other','','short','99'])
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}'
    catalog = {f['name']: f for f in client.get(base + '/fields', params={'project': 'A'}).json()}
    assert catalog['Team label'] == {'name': 'Team label', 'populated': 2, 'distinct': 2, 'occurrences': 2, 'chartable': True}
    assert not catalog['Long notes']['chartable']
    assert not catalog['Unique value']['chartable']
    scope = {'project': 'A', 'sprint': 'Sprint 1', 'field': 'Team label'}
    data = client.get(base + '/field-analytics', params=scope).json()
    assert data['multiple_values'] and data['populated'] == 2 and data['issues'] == 2
    assert {v['value']: v['count'] for v in data['values']} == {'Alpha': 2,'Beta': 1}
    for value in data['values']:
        assert client.get(base + '/issues', params={**scope,'field_value': value['value']}).json()['total'] == value['count']
    all_values = client.get(base + '/field-analytics', params={'field': 'Team label','project': 'A'}).json()['values']
    blank = next(v for v in all_values if v['missing'])
    assert blank['count'] == 49
    assert client.get(base + '/issues', params={'field': 'Team label','project': 'A','field_missing': True}).json()['total'] == 49
    assert client.get(base + '/field-analytics', params={'field': 'Long notes'}).status_code == 400
    assert client.get(base + '/field-analytics', params={'field': 'Unique value'}).status_code == 400
    assert client.get(base + '/field-analytics', params={'field': 'Unknown'}).status_code == 400
    assert client.get(base + '/issues', params={'field': 'Unknown','field_value': 'x'}).status_code == 400
    assert client.get(base + '/field-analytics', params={**scope,'sprint': '__unscheduled__'}).json()['issues'] == 0


def test_parent_links_types_cross_sprints_missing_parents_and_filters(client):
    headers = ['Issue key','Issue id','Summary','Status','Issue Type','Sprint','Parent','Parent key','Epic Link']
    rows = [
        ['A-1','101','Real parent','Open','Bug','Sprint 1','','',''],
        ['A-2','102','Child by ID','Open','Task','Sprint 2','101','',''],
        ['A-3','103','Grandchild','Open','Sub-task','Sprint 2','','A-2',''],
        ['A-4','104','Epic fallback child','Open','Story','','','','A-1'],
        ['A-5','105','Empty epic','Open','Epic','','','',''],
        ['A-6','106','External parent','Open','Task','','','OUTSIDE-1',''],
    ]
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}'
    parent = client.get(base + '/issues/A-1').json()
    assert parent['is_parent'] and parent['child_count'] == 2 and parent['type'] == 'Bug'
    assert {i['key'] for i in parent['children']} == {'A-2','A-4'}
    child = client.get(base + '/issues/A-2').json()
    assert child['has_parent'] and child['is_parent'] and child['parent']['key'] == 'A-1'
    assert child['children'][0]['key'] == 'A-3'
    assert not client.get(base + '/issues/A-5').json()['is_parent']
    external = client.get(base + '/issues/A-6').json()
    assert external['parent'] is None and not external['parent_in_export'] and external['has_parent']
    assert external['parent_key'] == 'OUTSIDE-1'
    assert client.get(base + '/issues', params={'relationship': 'parents'}).json()['total'] == 2
    assert client.get(base + '/issues', params={'relationship': 'children'}).json()['total'] == 4
    assert client.get(base + '/issues', params={'relationship': 'standalone'}).json()['items'][0]['key'] == 'A-5'
    assert client.get(base + '/issues', params={'relationship': 'parents','sprint': 'Sprint 2'}).json()['total'] == 1
    assert client.get(base + '/issues', params={'relationship': 'invalid'}).status_code == 400


def test_parent_cycles_and_ambiguous_ids_do_not_create_false_parents(client):
    headers = ['Issue key','Issue id','Summary','Status','Issue Type','Parent','Parent key']
    rows = [['A-1','1','A','Open','Task','','A-2'],['A-2','2','B','Open','Task','','A-1'],['A-3','3','C','Open','Task','3',''],['A-4','4','D','Open','Task','',''],['A-5','4','E','Open','Task','',''],['A-6','6','F','Open','Task','4','']]
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}'
    assert client.get(base + '/issues', params={'relationship': 'parents'}).json()['total'] == 0
    for key in ['A-1','A-2','A-3']:
        detail = client.get(base + '/issues/' + key).json()
        assert detail['hierarchy_warning'] and not detail['has_parent']
        assert detail['parent'] is None
    unresolved = client.get(base + '/issues/A-6').json()
    assert unresolved['parent'] is None and unresolved['parent_id'] == '4'
    assert unresolved['parent_key'] == ''


def test_restart_backfills_optional_fields_and_hierarchy_without_changing_source(client):
    headers = ['Issue key','Issue id','Summary','Status','Issue Type','Parent','Original estimate','Resolution','Something new']
    rows = [['A-1','1','Parent','Done','Bug','','3600','Fixed','x'],['A-2','2','Child','Review','Task','1','1800','','y']]
    dataset = upload(client, encode(rows, headers))
    original = [(r['key'], r['details']) for r in store.mongo().issues.find({'dataset_id': dataset})]
    for issue in store.summaries(dataset):
        for field in ['normalization_version','original_seconds','resolution','is_parent','has_parent','child_count','parent_key','parent_id','issue_id']:
            issue.pop(field, None)
        store.mongo().issues.update_one({'dataset_id': dataset, 'key': issue['key']}, {'$set': {'summary': issue}})
    store.initialize()
    store.initialize()
    parent = client.get(f'/api/datasets/{dataset}/issues/A-1').json()
    assert parent['is_parent'] and parent['child_count'] == 1 and parent['resolution'] == 'Fixed'
    assert parent['original_seconds'] == 3600
    assert client.get(f'/api/datasets/{dataset}/issues/A-2').json()['parent']['key'] == 'A-1'
    assert [(r['key'], r['details']) for r in store.mongo().issues.find({'dataset_id': dataset})] == original


def test_ticket_numbers_ids_and_repeated_link_columns_show_titles(client):
    headers = ['Issue key','Issue id','Summary','Status','Issue Type','Parent','Inward issue link (Blocks)','Inward issue link (Blocks)','Story Points']
    rows = [['A-7','1007','Parent title','Open','Story','','','','7'],['A-232','1232','Child title','Review','Task','7','1007','A-7','232'],['B-7','2007','Other project parent','Open','Task','','','',''],['B-8','2008','Other child','Open','Task','7','','','']]
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}'
    child = client.get(base + '/issues/A-232').json()
    assert child['parent_key'] == 'A-7' and child['parent_title'] == 'Parent title'
    assert child['display_fields']['Parent'][0] == [{'text': 'Parent title','key': 'A-7'}]
    assert child['display_fields']['Inward issue link (Blocks)'] == [[{'text': 'Parent title','key': 'A-7'}],[{'text': 'Parent title','key': 'A-7'}]]
    assert child['display_fields']['Story Points'][0] == [{'text': '232'}]
    assert child['display_fields']['Issue id'][0] == [{'text': 'Child title','key': 'A-232'}]
    assert child['fields']['Parent'] == ['7']  # Original CSV is unchanged.
    assert client.get(base + '/issues/B-8').json()['parent_title'] == 'Other project parent'
    values = client.get(base + '/field-analytics', params={'field': 'Parent', 'project': 'A'}).json()['values']
    assert next(v for v in values if not v['missing'])['label'] == 'Parent title'


def test_reference_conflicts_and_missing_targets_are_explicit(client):
    headers = ['Issue key','Issue id','Summary','Status','Issue Type','Parent','Related tickets']
    rows = [['A-7','70','Ticket seven','Open','Task','',''],['A-8','7','ID seven belongs here','Open','Task','',''],['A-9','90','Conflicting child','Open','Task','7','A-999'],['A-10','100','Missing child','Open','Task','232','']]
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}'
    conflict = client.get(base + '/issues/A-9').json()
    assert conflict['parent'] is None and conflict['parent_reference_problem'] == 'ambiguous'
    assert conflict['display_fields']['Parent'][0][0]['reason'] == 'ambiguous'
    assert conflict['display_fields']['Related tickets'][0][0]['text'] == 'Ticket not included in export'
    missing = client.get(base + '/issues/A-10').json()
    assert missing['parent_reference_problem'] == 'not_in_export'
    assert any('could not be uniquely matched' in w for w in store.dataset(dataset)['metadata']['warnings'])


def test_status_order_colors_save_filter_and_restart(client):
    dataset = upload(client)
    base = f'/api/datasets/{dataset}'
    config = client.get(base + '/workflow', params={'project': 'DEMO'}).json()
    config['order'] = ['Testing','Production','Test Complete','Done','To Do']
    config['colors']['Testing'] = '#123ABC'
    saved = client.put(base + '/workflow', params={'project': 'DEMO'}, json=config)
    assert saved.status_code == 200
    store.initialize()
    data = client.get(base + '/analytics', params={'project': 'DEMO','sprint': 'Sprint 10'}).json()
    assert [g['label'] for g in data['stages']] == config['order']
    assert [g['label'] for g in data['sprint']['stages']] == config['order']
    assert data['stages'][0]['color'] == '#123abc'
    assert data['sprint']['stages'][0]['color'] == '#123abc'
    assert client.get(base + '/issues', params={'project': 'DEMO', 'stage': data['stages'][0]['id']}).json()['total'] == data['stages'][0]['count']
    invalid = {**config, 'order': ['Testing'] * 5}
    assert client.put(base + '/workflow', params={'project': 'DEMO'}, json=invalid).status_code == 422
    invalid = {**config, 'colors': {**config['colors'], 'Done': 'red;bad'}}
    assert client.put(base + '/workflow', params={'project': 'DEMO'}, json=invalid).status_code == 422
    assert client.get(base + '/workflow', params={'project': 'DEMO'}).json()['order'] == config['order']


def test_people_observed_mix_explicit_developer_labels_and_project_scope(client):
    dataset = upload(client)
    base = f'/api/datasets/{dataset}'
    data = client.get(base + '/people', params={'project': 'DEMO','sprint': 'Sprint 9'}).json()
    assert data['assigned_people'] == 2 and data['developer_count'] == 0 and data['selected_people'] == 1
    assert data['other_member_count'] == 2
    ana = next(p for p in data['people'] if p['assignee'] == 'Ana')
    assert ana['total'] == 2 and ana['selected_total'] == 1
    assert {t['name']: t['count'] for t in ana['types']} == {'Story': 1,'Task': 1}
    profiles = [{'project': 'DEMO','assignee': 'Ana','work_areas': ['Backend','Lead'], 'is_developer': True}, {'project': 'OTHER','assignee': 'Cam','work_areas': ['Data'], 'is_developer': False}]
    assert client.put(base + '/people', json={'people': profiles}).status_code == 200
    store.initialize()
    data = client.get(base + '/people', params={'project': 'DEMO'}).json()
    assert data['developer_count'] == 1
    assert data['other_member_count'] == 1
    assert data['assigned_people'] == data['developer_count'] + data['other_member_count']
    assert data['work_areas'] == [{'name': 'Backend','count': 1},{'name': 'Lead','count': 1}]
    other = client.get(base + '/people', params={'project': 'OTHER'}).json()
    assert other['developer_count'] == 0 and other['other_member_count'] == 1
    invalid = [{**profiles[0], 'is_developer': False}, {**profiles[1], 'assignee': 'Unknown'}]
    assert client.put(base + '/people', json={'people': invalid}).status_code == 422
    assert client.get(base + '/people', params={'project': 'DEMO'}).json()['developer_count'] == 1
    invalid = [{**profiles[0], 'work_areas': ['x' * 81]}]
    assert client.put(base + '/people', json={'people': invalid}).status_code == 422
    assert client.put(base + '/people', json={'people': [{**profiles[0], 'is_developer': 'yes'}]}).status_code == 422


def test_non_comma_csv_gives_actionable_message(client):
    dataset = upload(client, b'Issue key;Summary;Status;Issue Type\nA-1;A;Open;Task')
    assert store.dataset(dataset)['status'] == 'failed'
    assert 'comma-separated CSV UTF-8' in store.dataset(dataset)['message']


def test_sprint_people_counts_distinct_roles_overlap_blanks_and_project_scope(client):
    headers = ['Issue key','Summary','Status','Issue Type','Sprint','Assignee','Reporter']
    rows = [
        ['A-1','One','Open','Task','Sprint 1','Ana','Ana'],
        ['A-2','Two','Open','Task','Sprint 1','Ana','Ben'],
        ['A-3','Three','Done','Bug','Sprint 1','','Ben'],
        ['A-4','Four','Open','Task','Sprint 2','Cam',''],
        ['A-5','Five','Open','Task','','',''],
        ['B-1','Other project','Open','Task','Sprint 1','Dee','Eli'],
    ]
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}/analytics'
    first = client.get(base, params={'project':'A','sprint':'Sprint 1'}).json()['sprint']['metrics']
    assert (first['assignee_count'],first['reporter_count'],first['people_count']) == (1,2,2)
    second = client.get(base, params={'project':'A','sprint':'Sprint 2'}).json()['sprint']['metrics']
    assert (second['assignee_count'],second['reporter_count'],second['people_count']) == (1,0,1)
    combined = client.get(base, params={'sprint':'Sprint 1'}).json()['sprint']['metrics']
    assert (combined['assignee_count'],combined['reporter_count'],combined['people_count']) == (2,3,4)
    empty = client.get(base, params={'sprint':'__unscheduled__'}).json()['sprint']['metrics']
    assert empty['assignee_count'] == empty['reporter_count'] == empty['people_count'] == 0
    project = client.get(base, params={'project':'A'}).json()['sprint']['metrics']
    assert (project['assignee_count'],project['reporter_count'],project['people_count']) == (2,2,3)
    missing = upload(client, b'Issue key,Summary,Status,Issue Type\nC-1,Missing optional people,Open,Task\n')
    no_people = client.get(f'/api/datasets/{missing}/analytics').json()['sprint']['metrics']
    assert no_people['assignee_count'] == no_people['reporter_count'] == no_people['people_count'] == 0


def test_inactive_members_keep_history_roles_and_can_be_reactivated(client):
    dataset = upload(client)
    base = f'/api/datasets/{dataset}'
    profile = {'project': 'DEMO','assignee': 'Ana','work_areas': ['Backend','Lead'],'is_developer': True,'is_active': False}
    assert client.put(base + '/people', json={'people': [profile]}).status_code == 200
    store.initialize()
    team = client.get(base + '/people', params={'project': 'DEMO'}).json()
    assert team['assigned_people'] == 2
    assert team['developer_count'] == 0 and team['other_member_count'] == 1 and team['inactive_member_count'] == 1
    ana = next(p for p in team['people'] if p['assignee'] == 'Ana')
    assert not ana['is_active'] and ana['is_developer'] and ana['work_areas'] == ['Backend','Lead']
    assert ana['total'] == 2 and len(ana['types']) == 2
    sprint = client.get(base + '/analytics', params={'project': 'DEMO','sprint': 'Sprint 10'}).json()['sprint']['metrics']
    assert sprint['assignee_count'] == 2 and sprint['total'] == 4
    assert client.get(base + '/issues/DEMO-1').json()['assignee'] == 'Ana'
    # An older client editing roles must not silently reactivate an inactive member.
    legacy = {k: v for k, v in profile.items() if k != 'is_active'}
    assert client.put(base + '/people', json={'people': [legacy]}).status_code == 200
    assert client.get(base + '/people', params={'project': 'DEMO'}).json()['inactive_member_count'] == 1
    assert client.put(base + '/people', json={'people': [{**profile,'is_active': 'false'}]}).status_code == 422
    assert client.get(base + '/people', params={'project': 'DEMO'}).json()['inactive_member_count'] == 1
    assert client.put(base + '/people', json={'people': [{**profile,'is_active': True}]}).status_code == 200
    active = client.get(base + '/people', params={'project': 'DEMO'}).json()
    assert active['developer_count'] == 1 and active['inactive_member_count'] == 0
    assert active['assigned_people'] == active['developer_count'] + active['other_member_count'] + active['inactive_member_count']


def test_membership_defaults_and_deduplication_across_projects(client):
    headers = ['Issue key','Summary','Status','Issue Type','Assignee']
    rows = [['A-1','A','Open','Task','Alex'],['B-1','B','Open','Task','Alex']]
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}'
    old = {'project':'A','assignee':'Alex','work_areas':['Backend'],'is_developer':True}
    store.save_people(dataset, [old])  # Pre-membership stored profiles remain active.
    assert client.get(base + '/people', params={'project':'A'}).json()['people'][0]['is_active']
    assert client.put(base + '/people', json={'people': [{**old,'is_active':False}]}).status_code == 200
    combined = client.get(base + '/people').json()
    assert combined['assigned_people'] == 1 and combined['inactive_member_count'] == 0
    assert combined['developer_count'] == 0 and combined['other_member_count'] == 1
    assert client.get(base + '/people', params={'project':'A'}).json()['inactive_member_count'] == 1


def test_sprint_role_chart_counts_distinct_people_and_scopes_assignments(client):
    headers = ['Issue key','Summary','Status','Issue Type','Assignee','Sprint']
    rows = [['A-1','A','Open','Task','Alex','Sprint 1'], ['A-2','B','Open','Task','Alex','Sprint 1'], ['A-3','C','Done','Bug','Sam','Sprint 2']]
    dataset = upload(client, encode(rows, headers))
    base = f'/api/datasets/{dataset}'
    profiles = [{'project':'A','assignee':'Alex','work_areas':['Backend','Lead'],'is_developer':True}, {'project':'A','assignee':'Sam','work_areas':['Backend'],'is_developer':False,'is_active':False}]
    assert client.put(base + '/people', json={'people': profiles}).status_code == 200
    all_work = client.get(base + '/people').json()
    assert all_work['work_areas'] == [{'name':'Backend','count':2},{'name':'Lead','count':1}]
    first = client.get(base + '/people', params={'sprint':'Sprint 1'}).json()
    assert first['selected_role_people'] == first['selected_people'] == 1
    assert first['selected_work_areas'] == [{'name':'Backend','count':1},{'name':'Lead','count':1}]
    second = client.get(base + '/people', params={'sprint':'Sprint 2'}).json()
    assert second['selected_role_people'] == 1  # Historical sprint still includes an inactive member.
    assert second['selected_work_areas'] == [{'name':'Backend','count':1}]
    assert client.get(base + '/people', params={'sprint':'__unscheduled__'}).json()['selected_work_areas'] == []
