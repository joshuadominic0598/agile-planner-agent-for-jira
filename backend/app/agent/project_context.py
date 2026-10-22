"""User-owned project briefs, isolated by imported snapshot and project."""

from . import prompt_versions

MAX_CHARS = 12000


def read(dataset_id, project='', version_id=''):
    v = prompt_versions.get(dataset_id, version_id)
    row = next((b for b in v['briefs'] if b['project'] == project), None)
    return {
        'project': project,
        'content': row['content'] if row else '',
        'updated_at': v['created_at'] if row else None,
        'version_id': v['id'],
        'version_number': v['number'],
        'head_version_id': prompt_versions.head(dataset_id)['head_version_id'],
    }


def write(dataset_id, project, content, base_version_id=None):
    head = prompt_versions.head(dataset_id)
    active = prompt_versions.get(dataset_id)
    briefs = [b for b in active['briefs'] if b['project'] != project]
    briefs.append({'project': project, 'content': content})
    prompt_versions.save(
        dataset_id,
        prompt_versions.PromptWrite(
            base_version_id=base_version_id or head['head_version_id'],
            briefs=briefs,
            change_note='Saved project context in Sprint Agent',
        ),
        activate=True,
    )
    return read(dataset_id, project)


def for_question(context):
    chosen = getattr(context, 'conversation_memory', {}).get('project')
    chosen = context.project if chosen is None else chosen
    v = prompt_versions.get(context.dataset_id, getattr(context, 'prompt_version_id', ''))
    rows = [dict(b, version_id=v['id'], version_number=v['number']) for b in v['briefs'] if b['content']]
    relevant = [
        dict(row)
        for row in rows
        if not row['project'] or chosen in {'', '__all__'} or row['project'] == chosen
    ]
    result = []
    remaining = 16000
    for row in relevant[:50]:
        content = row['content'][: min(4000, remaining)]
        remaining -= len(content)
        result.append({**row, 'content': content, 'truncated': len(content) < len(row['content'])})
    if len(relevant) > 50:
        result.append(
            {
                'omitted_briefs': len(relevant) - 50,
                'note': 'Fetch a specific project brief with get_project_context.',
            }
        )
    return result
