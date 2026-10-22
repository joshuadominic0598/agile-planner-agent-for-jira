from app import store
from app.agent import project_context, prompt_versions
from app.agent.tools import Context
from app.observability.dashboard import app
from fastapi.testclient import TestClient
from test_conversations import client as context_client
from test_operations import sample

client = context_client


def test_legacy_prompt_migrates_once_and_revisions_are_immutable(client):
    dataset = sample(client)
    store.mongo().agent_project_context.insert_one(
        {'dataset_id': dataset, 'project': 'APP', 'content': 'Legacy team goals', 'updated_at': 'old'}
    )
    with TestClient(app) as ops:
        base = '/api/ops/evaluation/prompts/' + dataset
        catalog = ops.get(base).json()
        v1 = catalog['versions'][0]
        assert v1['number'] == 1 and v1['briefs'][0]['content'] == 'Legacy team goals'
        value = {'base_version_id': v1['id'], 'briefs': [{'project': 'APP', 'content': 'New goals'}]}
        response = ops.post(base, json=value)
        assert response.status_code == 201
        v2 = response.json()
        assert v2['number'] == 2 and project_context.read(dataset, 'APP')['content'] == 'Legacy team goals'
        assert ops.post(base, json=value).status_code == 409
        assert prompt_versions.get(dataset, v1['id'])['briefs'][0]['content'] == 'Legacy team goals'
        assert ops.post(base + '/activate', json={'version_id': v2['id']}).status_code == 200
        assert project_context.read(dataset, 'APP')['content'] == 'New goals'
        ops.post(base + '/activate', json={'version_id': v1['id']})
        assert project_context.read(dataset, 'APP')['content'] == 'Legacy team goals'
        assert len(ops.get(base).json()['versions']) == 2


def test_prompt_versions_are_export_scoped_and_tool_reads_the_pinned_revision(client):
    first, second = sample(client), sample(client)
    original = project_context.write(first, 'APP', 'Prioritize cache reliability')
    ctx = Context(first, 'APP')
    ctx.prompt_version_id = original['version_id']
    project_context.write(first, 'APP', 'Prioritize new features')
    result = ctx.call('get_project_context', {'project': 'APP'})
    assert result['project_brief']['content'] == 'Prioritize cache reliability'
    assert project_context.for_question(ctx)[0]['content'] == 'Prioritize cache reliability'
    with TestClient(app) as ops:
        response = ops.post(
            f'/api/ops/evaluation/prompts/{second}/activate', json={'version_id': original['version_id']}
        )
        assert response.status_code == 404
        catalog = ops.get(f'/api/ops/evaluation/prompts/{second}').json()
        invalid = ops.post(
            f'/api/ops/evaluation/prompts/{second}',
            json={
                'base_version_id': catalog['head_version_id'],
                'briefs': [{'project': 'OTHER', 'content': 'No'}],
            },
        )
        assert invalid.status_code == 422


def test_agent_project_context_save_activates_new_revision_and_rejects_stale_edits(client):
    dataset = sample(client)
    endpoint = f'/api/datasets/{dataset}/agent/project-context'
    baseline = client.get(endpoint).json()
    value = {'content': 'Release reliability goals', 'base_version_id': baseline['head_version_id']}
    saved = client.put(endpoint, json=value)
    assert saved.status_code == 200 and saved.json()['version_number'] == 2
    assert client.put(endpoint, json=value).status_code == 409
    assert project_context.read(dataset)['content'] == 'Release reliability goals'
