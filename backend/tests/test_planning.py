"""Planning rules, narrative evidence and constrained model proposals."""

import csv
import io
import json
from types import SimpleNamespace

import pytest
from app import planning, store
from app.agent import index, transport
from app.agent.tools import Context
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('JIRA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JIRA_AI_PROVIDER', 'disabled')
    monkeypatch.setenv('JIRA_EMBEDDING_PROVIDER', 'local')
    with TestClient(app) as client:
        yield client


def upload(client):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            'Issue key',
            'Summary',
            'Issue Type',
            'Status',
            'Status Category',
            'Project key',
            'Assignee',
            'Sprint',
            'Story Points',
            'Remaining Estimate',
            'Original Estimate',
            'Parent',
            'Description',
            'Acceptance Criteria',
            'Comment',
            'Attachment',
            'Priority',
        ]
    )
    writer.writerows(
        [
            [
                'APP-1',
                'Identity parent',
                'Epic',
                'Dev',
                'In Progress',
                'APP',
                'Ben',
                'Iteration 1',
                20,
                72000,
                108000,
                '',
                'Identity work',
                '',
                '',
                '',
                'High',
            ],
            [
                'APP-2',
                'Token rotation',
                'Story',
                'Dev',
                'In Progress',
                'APP',
                'Ana',
                'Iteration 1',
                3,
                7200,
                14400,
                '1',
                'Rotate sessions',
                'Reject old tokens after rotation',
                'A unique audit note',
                'https://example.invalid/design.pdf',
                'High',
            ],
            [
                'APP-3',
                'Token cleanup',
                'Task',
                'QA',
                'In Progress',
                'APP',
                '',
                'Iteration 1',
                2,
                3600,
                7200,
                '1',
                'Rotate sessions safely',
                '',
                '',
                '',
                'High',
            ],
            [
                'APP-4',
                'Released login',
                'Story',
                'Prod',
                'Done',
                'APP',
                'Ana',
                'Iteration 1',
                5,
                0,
                18000,
                '',
                'Released',
                '',
                '',
                '',
                'Medium',
            ],
            [
                'APP-5',
                'Unknown work',
                'Task',
                'To Do',
                'To Do',
                'APP',
                'Unknown',
                'Iteration 1',
                '',
                '',
                '',
                '',
                'No estimates',
                '',
                '',
                '',
                'Medium',
            ],
            [
                'APP-6',
                'Old work',
                'Task',
                'To Do',
                'To Do',
                'APP',
                'Inactive',
                'Iteration 0',
                2,
                3600,
                7200,
                '',
                'Old',
                '',
                '',
                '',
                'Low',
            ],
        ]
    )
    response = client.post(
        '/api/imports', files={'file': ('planning.csv', out.getvalue().encode(), 'text/csv')}
    )
    dataset = response.json()['id']
    store.save_people(
        dataset,
        [
            {
                'project': 'APP',
                'assignee': name,
                'is_developer': name != 'Ben',
                'is_active': name != 'Inactive',
                'work_areas': ['Backend'],
            }
            for name in ['Ana', 'Ben', 'Unknown', 'Inactive']
        ],
    )
    return dataset


def config(**kwargs):
    return planning.PlanningConfig(
        **{'project': 'APP', 'sprint': 'Iteration 1', 'budget': 10, 'basis': 'open', **kwargs}
    )


def test_points_scope_roles_parent_counting_and_unknowns(client):
    dataset = upload(client)
    report = planning.report(dataset, config(focus_priorities=['High']))
    assert report['metrics']['backlog_tickets'] == 4
    assert report['metrics']['known_estimate'] == 5
    assert report['metrics']['missing_estimates'] == 1
    assert report['metrics']['focus_priority'] == 3
    assert report['metrics']['focus_priority_known_estimate'] == 5
    assert report['metrics']['focus_priority_missing_estimates'] == 0
    people = {p['name']: p for p in report['people']}
    assert people['Ana']['headroom'] == 7
    assert people['Ana']['roles'] == ['Backend']
    assert people['Ben']['headroom'] is None
    assert people['Unknown']['headroom'] is None
    assert not people['Inactive']['eligible']
    assert not next(ticket for ticket in report['tickets'] if ticket['key'] == 'APP-1')['estimate_counted']


def test_hours_finished_stages_and_whole_project(client):
    dataset = upload(client)
    report = planning.report(
        dataset,
        config(unit='hours', completion='statuses', finished_statuses=['Prod', 'QA'], roster='configured'),
    )
    assert report['metrics']['backlog_tickets'] == 3
    people = {p['name']: p for p in report['people']}
    assert people['Ana']['known_load'] == 2
    assert people['Ana']['headroom'] == 8
    # Parent excluded across assignees, not just inside one person's list.
    assert people['Ben']['known_load'] == 0
    assert (
        planning.report(dataset, planning.PlanningConfig(project='APP', scope='project'))['metrics'][
            'backlog_tickets'
        ]
        == 5
    )
    all_work = planning.report(dataset, config(basis='all'))
    assert next(p for p in all_work['people'] if p['name'] == 'Ana')['headroom'] == 2


def test_parent_overlaps_invalidate_capacity_even_across_people(client):
    dataset = upload(client)
    report = planning.report(dataset, config(parent_policy='all_estimated', roster='configured'))
    assert report['metrics']['known_estimate'] == 25
    assert all(p['headroom'] is None for p in report['people'])


def test_settings_persist_and_validate_scope(client):
    dataset = upload(client)
    base = f'/api/datasets/{dataset}/planning'
    response = client.put(base + '/settings', json=config().model_dump())
    assert response.status_code == 200
    assert client.get(base + '/settings?project=APP').json()['budget'] == 10
    ctx = Context(dataset, 'APP')
    result = ctx.call('get_backlog_report', {'project': 'APP'})
    assert result['metrics']['backlog_tickets'] == 4
    for bad in [
        dict(project=''),
        dict(completion='statuses'),
        dict(sprint='missing'),
        dict(budget=-1),
        dict(finished_statuses=['unknown']),
    ]:
        payload = {**config().model_dump(), **bad}
        assert client.post(base + '/report', json=payload).status_code == 422


def test_plan_partition_and_combined_capacity_validation(client):
    dataset = upload(client)
    report = planning.report(dataset, config())
    ctx = SimpleNamespace(
        planning_report=report,
        planning_keys=[t['key'] for t in report['tickets']],
        planning_reserved={},
        planning_plan=None,
    )
    groups = [{'name': 'Identity', 'keys': ctx.planning_keys}]
    assert planning.validate_plan(
        ctx, groups, [{'key': 'APP-3', 'person': 'Ana', 'reason': 'Backend session work'}]
    )['accepted']
    assert ctx.planning_reserved == {'Ana': 2}
    with pytest.raises(ValueError):
        planning.validate_plan(
            ctx, [{'name': 'Duplicate', 'keys': ctx.planning_keys + [ctx.planning_keys[0]]}], []
        )
    with pytest.raises(ValueError):
        planning.validate_plan(ctx, groups, [{'key': 'APP-5', 'person': 'Ana', 'reason': 'No estimate'}])
    with pytest.raises(ValueError):
        planning.validate_plan(ctx, groups, [{'key': 'APP-2', 'person': 'Ana', 'reason': 'Already assigned'}])
    ctx.planning_reserved = {'Ana': 6}
    with pytest.raises(ValueError):
        planning.validate_plan(
            ctx, groups, [{'key': 'APP-3', 'person': 'Ana', 'reason': 'Would exceed total'}]
        )
    assert ctx.planning_reserved == {'Ana': 6}


def test_demo_download_import_and_rich_index(client):
    response = client.get('/api/demo.csv')
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.text)))
    assert len(rows) == 101
    assert len(rows[0]) == 31
    assert all(len(row) == len(rows[0]) for row in rows)
    assert all('DEMO-' in row[0] for row in rows[1:])
    uploaded = client.post('/api/imports', files={'file': ('demo.csv', response.content, 'text/csv')}).json()[
        'id'
    ]
    data = client.get(f'/api/imports/{uploaded}').json()
    assert data['metadata']['issue_count'] == 100
    assert {r['status'] for r in store.summaries(uploaded)} == {'To Do', 'In Progress', 'Dev', 'QA', 'Prod'}
    assert data['metadata']['repeated_columns']['Comment'] == 2
    dataset = upload(client)
    raw = store.issue(dataset, 'APP-2')
    text = index.document(raw['summary'], store.field_rows(dataset)['APP-2'])
    assert 'Reject old tokens' in text and 'unique audit note' in text and 'design.pdf' in text
    assert 'https://' not in text and 'Ana' not in text and 'Iteration 1' not in text
    index.build(dataset)
    result = index.hybrid_search(dataset, 'unique audit note', limit=3)
    assert result[0]['key'] == 'APP-2'


def model_reply(protocol, content, call=None):
    if protocol == 'responses':
        return {
            'output': [{'type': 'function_call', 'call_id': 'plan-1', **call}]
            if call
            else [{'type': 'message', 'content': [{'type': 'output_text', 'text': content}]}]
        }
    message = {'role': 'assistant', 'content': content}
    if call:
        message['tool_calls'] = [{'id': 'plan-1', 'type': 'function', 'function': call}]
    return {'choices': [{'message': message}]}


@pytest.mark.parametrize('adapter', ['compatible', 'openai'])
def test_ticket_analysis_retrieves_similar_work_and_streams_model_answer(client, monkeypatch, adapter):
    dataset = upload(client)
    index.build(dataset)
    monkeypatch.setenv('JIRA_AI_PROVIDER', adapter)
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setenv('JIRA_AI_MODEL', 'test-model')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://model/v1')
    prompts = []

    def request(client, url, headers, body, timeout, protocol, emit):
        prompts.append(json.dumps(body))
        if emit:
            emit('text_delta', {'text': 'Review token rotation and verify the rejection criteria.'})
        return model_reply(protocol, 'Review token rotation and verify the rejection criteria.')

    monkeypatch.setattr(transport, 'request', request)
    response = client.post(f'/api/datasets/{dataset}/analysis', json={'kind': 'ticket', 'key': 'APP-2'})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['event'] == 'done'
    assert any(e['event'] == 'text_delta' for e in events)
    assert 'Acceptance' in prompts[0] and 'similar_tickets' in prompts[0]
    assert 'APP-3' in prompts[0]
    assert any(t['tool'] == 'search_tickets' for t in events[-1]['tools'])


@pytest.mark.parametrize('adapter', ['compatible', 'openai'])
def test_backlog_analysis_requires_validated_model_groups(client, monkeypatch, adapter):
    dataset = upload(client)
    index.build(dataset)
    monkeypatch.setenv('JIRA_AI_PROVIDER', adapter)
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setenv('JIRA_AI_MODEL', 'qwen3:8b' if adapter == 'compatible' else 'test-model')
    monkeypatch.setenv('JIRA_AI_REASONING_EFFORT', 'high')
    monkeypatch.setenv('JIRA_AI_BASE_URL', 'http://model/v1')
    calls = []

    def request(client, url, headers, body, timeout, protocol, emit):
        calls.append(body)
        messages = body.get('messages', body.get('input', []))
        texts = json.dumps(messages)
        if 'batch_tickets' in texts and not any(
            m.get('role') == 'tool' or m.get('type') == 'function_call_output' for m in messages
        ):
            args = {
                'categories': {key: 'Identity' for key in ['APP-1', 'APP-2', 'APP-3', 'APP-5']},
                'assessments': {
                    key: 'Validate the identity requirement and confirm the missing planning inputs with the owner.'
                    for key in ['APP-1', 'APP-2', 'APP-3', 'APP-5']
                },
                'assignments': [
                    {'key': 'APP-3', 'person': 'Ana', 'reason': 'Backend work and explicit headroom'}
                ],
            }
            return model_reply(protocol, '', {'name': 'record_backlog_plan', 'arguments': json.dumps(args)})
        answer = 'Prioritize identity work; estimate the unknown ticket before committing more capacity.'
        if emit:
            emit('text_delta', {'text': answer})
        return model_reply(protocol, answer)

    monkeypatch.setattr(transport, 'request', request)
    response = client.post(
        f'/api/datasets/{dataset}/analysis', json={'kind': 'backlog', 'config': config().model_dump()}
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['event'] == 'done', events[-1]
    assert len(events[-1]['groups'][0]['keys']) == 4
    assert events[-1]['assignments'][0]['person'] == 'Ana'
    assert calls[0]['tool_choice'] == 'required'
    if adapter == 'compatible':
        assert calls[0]['reasoning_effort'] == 'none'
        assert '/no_think' in calls[0]['messages'][-1]['content']
        assert calls[-1]['reasoning_effort'] == 'high'
        assert '/no_think' not in calls[-1]['messages'][-1]['content']
    assert not store.mongo().issues.find_one(
        {'dataset_id': dataset, 'key': 'APP-3', 'summary.assignee': 'Ana'}
    )


def test_backlog_review_is_bounded_and_continues_without_duplicate_coverage(client, monkeypatch):
    from app import analysis_routes

    data = client.get('/api/demo.csv').content
    dataset = client.post('/api/imports', files={'file': ('demo.csv', data, 'text/csv')}).json()['id']
    cfg = planning.PlanningConfig(project='DEMO', scope='project')
    report = planning.report(dataset, cfg)
    batches, events = [], []

    def run(context, message, history, attached, allow_web, connection_id):
        if hasattr(context, 'planning_keys'):
            batches.append(list(context.planning_keys))
            assert len(context.planning_keys) <= 24
            planning.validate_plan(
                context,
                [{'name': 'Software delivery', 'keys': context.planning_keys}],
                [],
                {
                    key: 'Inspect this delivery requirement and confirm the next planning decision with its owner.'
                    for key in context.planning_keys
                },
            )
        else:
            assert (
                context.feature_evidence['ai_work_categories'][0]['count']
                == context.feature_evidence['review_coverage']['reviewed']
            )
            assert context.feature_evidence['people'][0]['usual_point_size']
            assert 'recent_sprint_work' in context.feature_evidence['people'][0]
            context.emit('text_delta', {'text': 'Refine the unestimated work before allocation.'})
        return 'Refine the unestimated work before allocation.', []

    monkeypatch.setattr(analysis_routes.provider, 'run', run)
    request = SimpleNamespace(app=app)
    body = analysis_routes.AnalysisRequest(kind='backlog', config=cfg)
    result = analysis_routes.run_backlog(
        dataset, body, request, {'model': 'test'}, lambda event, data: events.append((event, data))
    )
    assert len(batches) > 1
    assert len(set(key for batch in batches for key in batch)) == 20
    assert result['coverage']['reviewed'] == 20
    assert len(result['assessments']) == 20
    assert all(ticket['assessment'] for ticket in result['assessments'])
    assert result['coverage']['remaining'] == report['metrics']['backlog_tickets'] - 20
    assert result['coverage']['has_more']
    first_review_id = result['review_id']
    while result['coverage']['has_more']:
        body = analysis_routes.AnalysisRequest(kind='backlog', config=cfg, review_id=first_review_id)
        result = analysis_routes.run_backlog(dataset, body, request, {'model': 'test'}, lambda *a: None)
    visited = [key for batch in batches for key in batch]
    assert len(visited) == len(set(visited)) == report['metrics']['backlog_tickets']
    assert set(visited) == {t['key'] for t in report['tickets']}
    assert len(result['groups'][0]['keys']) == report['metrics']['backlog_tickets']
    assert result['fingerprint'] == report['fingerprint']
    assert events[-1][0] == 'text_delta'
    with pytest.raises(ValueError, match='already been reviewed'):
        analysis_routes.review_state(dataset, body, report)


def test_people_story_sizes_and_finished_sprint_points_are_snapshot_descriptions(client):
    dataset = upload(client)
    result = planning.report(dataset, config())
    ana = next(person for person in result['people'] if person['name'] == 'Ana')
    assert ana['assigned_total'] == 2
    assert ana['average_points_per_sprint'] == 8
    assert ana['average_points_sprint_count'] == 1
    assert all('points' in ticket for ticket in ana['recent_work'])
    assert ana['unfinished_total'] == 1
    assert ana['point_size_buckets'] == [
        {'name': 'Below 3 points', 'count': 0},
        {'name': '3 to below 5 points', 'count': 1},
        {'name': '5 points and above', 'count': 1},
    ]
    assert ana['sprint_work'] == [
        {
            'sprint': 'Iteration 1',
            'assigned_tickets': 2,
            'finished_tickets': 1,
            'known_finished_points': 5,
            'finished_without_points': 0,
        }
    ]
    assert result['metrics']['active_developers'] == 2
    assert result['metrics']['headroom_people'] == 1
    assert result['metrics']['overloaded_developers'] == 0
    change_ticket(dataset, 'APP-2', points=12)
    changed = planning.report(dataset, config())
    assert changed['metrics']['overloaded_developers'] == 1
    assert changed['metrics']['headroom_people'] == 0


def test_people_missing_points_overlap_and_epic_exclusion_do_not_invent_delivery(client):
    dataset = upload(client)
    change_ticket(dataset, 'APP-4', sprints=['Iteration 0', 'Iteration 1'], points=None)
    result = planning.report(dataset, config())
    ana = next(person for person in result['people'] if person['name'] == 'Ana')
    assert len(ana['sprint_work']) == 2
    assert all(
        row['known_finished_points'] == 0 and row['finished_without_points'] == 1
        for row in ana['sprint_work']
    )
    assert ana['point_unestimated_tickets'] == 1
    assert 'not historical' in ' '.join(result['notes'])
    change_ticket(dataset, 'APP-2', parent_key='')
    change_ticket(dataset, 'APP-3', parent_key='')
    store.mongo().issues.update_one(
        {'dataset_id': dataset, 'key': 'APP-1'}, {'$set': {'summary.is_parent': False}}
    )
    result = planning.report(dataset, config())
    assert not next(ticket for ticket in result['tickets'] if ticket['key'] == 'APP-1')['estimate_counted']


def test_continuation_rejects_changed_report_wrong_dataset_and_model(client):
    from app import analysis_routes

    dataset = upload(client)
    cfg = config()
    report = planning.report(dataset, cfg)
    state = {
        'id': 'review-example',
        'dataset_id': dataset,
        'fingerprint': report['fingerprint'],
        'connection_id': 'model-one',
        'next_offset': 1,
    }
    store.mongo().backlog_reviews.insert_one(state)
    body = analysis_routes.AnalysisRequest(
        kind='backlog', config=cfg, review_id=state['id'], connection_id='model-one'
    )
    assert analysis_routes.review_state(dataset, body, report)['next_offset'] == 1
    with pytest.raises(ValueError, match='changed'):
        analysis_routes.review_state(dataset, body, planning.report(dataset, config(budget=12)))
    with pytest.raises(ValueError, match='changed'):
        analysis_routes.review_state('another-import', body, report)
    body.connection_id = 'model-two'
    with pytest.raises(ValueError, match='model changed'):
        analysis_routes.review_state(dataset, body, report)


@pytest.mark.parametrize('window', [4096, 32768])
def test_native_backlog_batch_and_summary_fit_configured_window(client, monkeypatch, window):
    from app import analysis_routes
    from app.agent import context_budget, provider

    dataset = upload(client)
    cfg = {
        'configured': True,
        'provider': 'openai',
        'model': 'test-model',
        'base': 'http://model/v1',
        'key': 'synthetic',
        'context_window': window,
        'reasoning_effort': '',
    }
    monkeypatch.setattr(provider, 'resolve', lambda *args: cfg)
    calls = []

    def request(client, url, headers, body, timeout, protocol, emit):
        calls.append(body)
        assert (
            context_budget.estimate(body)
            <= int(window * 0.9) - context_budget.settings(cfg)['output_reserve']
        )
        tool = next(
            (tool for tool in body.get('tools', []) if tool.get('name') == 'record_backlog_plan'), None
        )
        message = next(
            item['content']
            for item in body['input']
            if isinstance(item.get('content'), str)
            and item['content'].startswith('Application-computed analysis evidence')
        )
        evidence = json.loads(message[message.index('{') :])
        if tool:
            keys = tool['parameters']['properties']['categories']['properties']
            assert {ticket['key'] for ticket in evidence['batch_tickets']} == set(keys)
            return model_reply(
                protocol,
                '',
                {
                    'name': 'record_backlog_plan',
                    'arguments': json.dumps(
                        {
                            'categories': {key: 'Identity' for key in keys},
                            'assignments': [],
                            'assessments': {
                                key: 'Validate the identity requirement and confirm missing inputs with its owner.'
                                for key in keys
                            },
                        }
                    ),
                },
            )
        assert evidence['report']['metrics']['backlog_tickets'] == 4
        assert any(person['name'] == 'Ana' for person in evidence['people'])
        return model_reply(protocol, 'Review this batch before choosing the next work items.')

    monkeypatch.setattr(transport, 'request', request)
    result = analysis_routes.run_backlog(
        dataset,
        analysis_routes.AnalysisRequest(kind='backlog', config=config()),
        SimpleNamespace(app=app),
        cfg,
        lambda *args: None,
    )
    assert result['coverage']['reviewed'] == 4
    assert result['content'].startswith('Review this batch')
    assert calls


def test_nested_estimates_exclude_ancestors_even_with_a_finished_middle_ticket(client):
    dataset = upload(client)
    for key, parent in [('APP-2', ''), ('APP-3', 'APP-4'), ('APP-4', 'APP-1')]:
        store.mongo().issues.update_one(
            {'dataset_id': dataset, 'key': key}, {'$set': {'summary.parent_key': parent}}
        )
    report = planning.report(dataset, config())
    assert report['metrics']['known_estimate'] == 5
    assert not next(t for t in report['tickets'] if t['key'] == 'APP-1')['estimate_counted']
    inclusive = planning.report(dataset, config(parent_policy='all_estimated'))
    assert all(p['headroom'] is None for p in inclusive['people'])


def test_project_is_a_per_sprint_scenario_and_selected_sprint_deducts_only_its_work(client):
    dataset = upload(client)
    whole = planning.report(
        dataset, planning.PlanningConfig(project='APP', scope='project', sprint='Iteration 0', budget=10)
    )
    sprint = planning.report(dataset, config())
    assert whole['config']['sprint'] == ''
    assert 'capacity_sprint' not in whole and 'capacity_sprint' not in whole['config']
    assert whole['metrics']['backlog_tickets'] == 5
    assert sprint['metrics']['backlog_tickets'] == 4
    assert 'APP-6' in {t['key'] for t in whole['tickets']}
    assert 'APP-6' not in {t['key'] for t in sprint['tickets']}
    whole_people = {p['name']: p for p in whole['people']}
    assert whole_people['Inactive']['known_load'] is None
    assert whole_people['Ana']['headroom'] is None
    assert whole_people['Ana']['allocation_room'] == 10
    assert whole_people['Ana']['budget'] == 10
    assert whole_people['Ana']['unit'] == 'points'
    assert whole['forecast']['minimum_sprints'] is None
    assert next(p for p in sprint['people'] if p['name'] == 'Inactive')['known_load'] == 0


def test_legacy_project_budget_is_not_reinterpreted_as_a_whole_project_budget(client):
    dataset = upload(client)
    store.mongo().planning_settings.insert_one(
        {
            'dataset_id': dataset,
            'project': 'APP',
            'config': {**config().model_dump(), 'scope': 'project', 'capacity_sprint': 'Iteration 1'},
        }
    )
    settings = client.get(f'/api/datasets/{dataset}/planning/settings?project=APP').json()
    assert settings['budget'] is None and settings['sprint'] == ''
    assert 'capacity_sprint' not in settings and settings['notice']


def test_planning_tool_schema_limits_allocations_to_valid_candidates(client):
    from app.agent.provider import analysis_tools
    from app.agent.tools import TOOLS

    dataset = upload(client)
    report = planning.report(dataset, config())
    ctx = SimpleNamespace(
        planning_report=report, planning_keys=[t['key'] for t in report['tickets']], planning_reserved={}
    )
    schema = next(t for t in analysis_tools(ctx) if t['name'] == 'record_backlog_plan')['parameters'][
        'properties'
    ]
    assert schema['assignments']['items']['properties']['key']['enum'] == ['APP-3']
    assert schema['assignments']['items']['properties']['person']['enum'] == ['Ana']
    original = next(t for t in TOOLS if t['name'] == 'record_backlog_plan')['parameters']['properties']
    assert 'enum' not in original['assignments']['items']['properties']['key']


def change_ticket(dataset, key, **fields):
    store.mongo().issues.update_one(
        {'dataset_id': dataset, 'key': key},
        {'$set': {f'summary.{field}': value for field, value in fields.items()}},
    )


def test_refinement_uses_existing_owner_and_unowned_gaps_require_triage(client):
    dataset = upload(client)
    change_ticket(dataset, 'APP-3', points=None, remaining_seconds=None, priority='')
    change_ticket(dataset, 'APP-5', priority='')
    result = planning.report(dataset, config())
    tickets = {t['key']: t for t in result['tickets']}
    assert tickets['APP-3']['readiness'] == 'triage'
    assert not tickets['APP-3']['refinement_owner']
    assert 'Reanalyse' in tickets['APP-3']['next_step']
    assert tickets['APP-5']['readiness'] == 'owner_refinement'
    assert tickets['APP-5']['refinement_owner'] == 'Unknown'
    assert 'estimate and priority' in tickets['APP-5']['next_step']
    assert tickets['APP-2']['readiness'] == 'ready'
    assert result['forecast']['minimum_sprints'] is None
    assert result['metrics']['triage'] == 1
    assert result['metrics']['owner_refinement'] == 1
    ctx = SimpleNamespace(planning_report=result, planning_keys=list(tickets), planning_reserved={})
    with pytest.raises(ValueError, match='awaiting priority'):
        planning.validate_plan(
            ctx,
            [{'name': 'Work', 'keys': list(tickets)}],
            [{'key': 'APP-3', 'person': 'Ana', 'reason': 'Not ready'}],
        )


def test_pending_priority_blocks_allocations_even_with_estimate(client):
    dataset = upload(client)
    result = planning.report(dataset, config(pending_priorities=['High']))
    tickets = {t['key']: t for t in result['tickets']}
    assert tickets['APP-3']['readiness'] == 'triage'
    assert tickets['APP-2']['readiness'] == 'owner_refinement'
    assert not tickets['APP-3']['priority_finalized']
    ctx = SimpleNamespace(planning_report=result, planning_keys=list(tickets), planning_reserved={})
    with pytest.raises(ValueError, match='awaiting priority'):
        planning.validate_plan(
            ctx,
            [{'name': 'Work', 'keys': list(tickets)}],
            [{'key': 'APP-3', 'person': 'Ana', 'reason': 'Not finalized'}],
        )


def test_individual_units_availability_and_settings_round_trip(client):
    dataset = upload(client)
    settings = config(
        resources={
            'Ana': {'unit': 'hours', 'budget': 6, 'available': True},
            'Unknown': {'unit': 'points', 'budget': 10, 'available': False},
        }
    )
    base = f'/api/datasets/{dataset}/planning'
    assert client.put(base + '/settings', json=settings.model_dump()).status_code == 200
    stored = client.get(base + '/settings?project=APP').json()
    assert stored['resources']['Ana'] == {'unit': 'hours', 'budget': 6, 'available': True}
    assert stored['capacity_cadence'] == 'per_sprint'
    result = planning.report(dataset, planning.PlanningConfig(**stored))
    people = {p['name']: p for p in result['people']}
    assert people['Ana']['unit'] == 'hours'
    assert people['Ana']['known_load'] == 2
    assert people['Ana']['headroom'] == 4
    assert not people['Unknown']['eligible']
    assert people['Unknown']['headroom'] is None
    ctx = SimpleNamespace(
        planning_report=result, planning_keys=[t['key'] for t in result['tickets']], planning_reserved={}
    )
    planning.validate_plan(
        ctx,
        [{'name': 'Work', 'keys': ctx.planning_keys}],
        [{'key': 'APP-3', 'person': 'Ana', 'reason': 'Backend experience'}],
    )
    assert ctx.planning_plan['assignments'][0]['estimate'] == 1
    assert ctx.planning_plan['assignments'][0]['unit'] == 'hours'
    assert ctx.planning_reserved == {'Ana': 1}
    change_ticket(dataset, 'APP-3', remaining_seconds=None)
    ctx.planning_report = planning.report(dataset, settings)
    with pytest.raises(ValueError, match='this person’s unit'):
        planning.validate_plan(
            ctx,
            [{'name': 'Work', 'keys': ctx.planning_keys}],
            [{'key': 'APP-3', 'person': 'Ana', 'reason': 'Points cannot replace hours'}],
        )
    invalid = settings.model_dump()
    invalid['resources']['Not a project person'] = {'unit': 'points', 'budget': 10}
    assert client.post(base + '/report', json=invalid).status_code == 422


def test_no_forecast_until_estimates_and_priorities_complete_and_units_stay_separate(client):
    dataset = upload(client)
    settings = config(scope='project', resources={'Unknown': {'unit': 'hours', 'budget': 40}})
    assert planning.report(dataset, settings)['forecast']['minimum_sprints'] is None
    change_ticket(dataset, 'APP-5', points=8, priority='')
    result = planning.report(dataset, settings)
    assert result['metrics']['missing_estimates'] == 0
    assert result['forecast']['minimum_sprints'] is None
    change_ticket(dataset, 'APP-5', priority='Medium')
    result = planning.report(dataset, settings)
    assert result['forecast']['capacity_per_sprint'] == 10
    assert result['forecast']['minimum_sprints'] == 2
    assert 'Theoretical' in result['forecast']['message']
    assert (
        planning.report(dataset, config(scope='project', pending_priorities=['Medium']))['forecast'][
            'minimum_sprints'
        ]
        is None
    )


def test_all_sprint_work_is_default_and_refinement_uses_persons_unit(client):
    dataset = upload(client)
    settings = planning.PlanningConfig(
        project='APP', sprint='Iteration 1', budget=10, resources={'Ana': {'unit': 'hours', 'budget': 10}}
    )
    change_ticket(dataset, 'APP-2', points=None)
    result = planning.report(dataset, settings)
    ana = next(p for p in result['people'] if p['name'] == 'Ana')
    ticket = next(t for t in result['tickets'] if t['key'] == 'APP-2')
    assert settings.basis == 'all'
    assert ana['known_load'] == 2
    assert ticket['readiness'] == 'ready'
    assert ticket['refinement_unit'] == 'hours'
    assert result['forecast']['minimum_sprints'] is None


def test_default_saved_rules_can_be_read_by_agent_before_any_configuration(client):
    dataset = upload(client)
    result = Context(dataset, 'APP').call('get_backlog_report', {'project': 'APP'})
    assert result['config']['scope'] == 'project'
    assert result['config']['capacity_cadence'] == 'per_sprint'
    assert result['metrics']['backlog_tickets'] == 5
    assert all(p['headroom'] is None and p['allocation_room'] is None for p in result['people'])


def test_batch_assessments_require_each_ticket_and_keep_source_narratives(client):
    from app.agent.context_budget import bound_result
    from app.agent.provider import analysis_tools

    dataset = upload(client)
    report = planning.report(dataset, config())
    keys = [ticket['key'] for ticket in report['tickets']]
    ctx = SimpleNamespace(
        planning_report=report, planning_keys=keys, planning_reserved={}, planning_assessment_required=True
    )
    groups = [{'name': 'Identity', 'keys': keys}]
    with pytest.raises(ValueError, match='Assess every batch ticket'):
        planning.validate_plan(ctx, groups, [], {})
    with pytest.raises(ValueError, match='specific finding'):
        planning.validate_plan(ctx, groups, [], {key: 'Looks fine' for key in keys})
    assessments = {
        key: 'Confirm the token-rotation acceptance criteria with the existing owner before sizing.'
        for key in keys
    }
    planning.validate_plan(ctx, groups, [], assessments)
    assert set(ctx.planning_plan['assessments']) == set(keys)
    schema = next(t for t in analysis_tools(ctx) if t['name'] == 'record_backlog_plan')['parameters']
    assert 'assessments' in schema['required']
    assert schema['properties']['assessments']['required'] == keys
    packet = json.loads(
        bound_result(
            {
                'current_batch': [
                    {
                        'key': keys[0],
                        'summary': 'Token rotation',
                        'assessment': assessments[keys[0]],
                        'narrative_excerpt': 'Rotate expiring refresh tokens with grace period.',
                        'readiness': 'owner_refinement',
                    }
                ]
            },
            {'provider': 'openai', 'model': 'test', 'context_window': 32768},
        )
    )
    assert packet['current_batch'][0]['narrative_excerpt'].startswith('Rotate expiring')
    assert packet['current_batch'][0]['assessment'] == assessments[keys[0]]


def test_assigned_sprint_average_uses_memberships_and_five_recent_point_samples():
    from app.planning_people import insights

    assigned = [
        {
            'key': f'APP-{n}',
            'summary': 'Delivery work',
            'status': 'In Progress',
            'points': points,
            'sprints': sprints,
            'updated': f'2026-01-{n:02}',
        }
        for n, (points, sprints) in enumerate(
            [(3, ['A', 'B']), (5, ['A']), (None, ['B']), (2, ['C']), (1, []), (None, ['A'])], 1
        )
    ]
    profile = insights(assigned, lambda rows: rows, lambda row: False)
    assert profile['average_points_per_sprint'] == 4.33
    assert profile['average_points_sprint_count'] == 3
    assert profile['sprint_point_unestimated_tickets'] == 2
    assert [ticket['key'] for ticket in profile['recent_work']] == [
        'APP-6',
        'APP-5',
        'APP-4',
        'APP-3',
        'APP-2',
    ]
    assert profile['recent_work'][-1]['points'] == 5
    assert (
        insights([{**assigned[0], 'points': None}], lambda rows: rows, lambda row: False)[
            'average_points_per_sprint'
        ]
        is None
    )
    assert (
        insights([{**assigned[0], 'points': 0}], lambda rows: rows, lambda row: False)[
            'average_points_per_sprint'
        ]
        == 0
    )
