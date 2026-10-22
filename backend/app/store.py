"""MongoDB is the source of truth after CSV import; no CSV reads during queries."""

import os
import re
from functools import lru_cache

from bson import BSON
from pymongo import MongoClient, ReplaceOne, UpdateOne

from . import recency


class RecordTooLarge(ValueError):
    pass


@lru_cache(maxsize=4)
def client(uri):
    return MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, appname='AgilePlanner')


def mongo():
    name = os.environ.get('JIRA_MONGO_DATABASE', 'sprintlens')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', name):
        raise ValueError('Use a plain MongoDB database name.')
    return client(os.environ.get('JIRA_MONGO_URI', 'mongodb://127.0.0.1:27018'))[name]


def initialize():
    db = mongo()
    db.command('ping')
    for name, keys in {
        'agent_runs': [('id', 1)],
        'agent_evaluations': [('id', 1)],
        'agent_eval_cases': [('id', 1)],
        'agent_eval_results': [('id', 1)],
        'agent_eval_datasets': [('id', 1)],
        'agent_eval_versions': [('id', 1)],
        'agent_eval_jobs': [('id', 1)],
        'datasets': [('id', 1)],
        'issues': [('dataset_id', 1), ('key', 1)],
        'people': [('dataset_id', 1), ('project', 1), ('assignee', 1)],
        'workflows': [('dataset_id', 1), ('project', 1)],
        'agent_connections': [('id', 1)],
        'planning_settings': [('dataset_id', 1), ('project', 1)],
        'backlog_reviews': [('id', 1)],
        'agent_project_context': [('dataset_id', 1), ('project', 1)],
        'agent_sessions': [('id', 1)],
        'agent_messages': [('id', 1)],
        'agent_session_memory': [('session_id', 1)],
    }.items():
        db[name].create_index(keys, unique=True)
    for field in (
        'project_key',
        'assignee',
        'reporter',
        'status',
        'category',
        'priority',
        'type',
        'sprints',
        'issue_id',
    ):
        db.issues.create_index([('dataset_id', 1), (f'summary.{field}', 1)])
    db.agent_runs.create_index([('session_id', 1), ('started_at', -1)])
    db.agent_runs.create_index([('dataset_id', 1), ('started_at', -1)])
    db.agent_eval_results.create_index([('evaluation_id', 1), ('case_id', 1)], unique=True)
    db.agent_sessions.create_index([('dataset_id', 1), ('created_at', -1)])
    db.agent_messages.create_index([('session_id', 1), ('id', -1)])
    db.backlog_reviews.create_index('updated_at', expireAfterSeconds=30 * 86400)
    from . import vector_store
    from .agent.index import initialize as initialize_index

    with vector_store.connect() as index_db:
        initialize_index(index_db)
    from .legacy_migration import migrate

    migrate()
    db.datasets.update_many(
        {'status': {'$in': ['queued', 'processing']}},
        {
            '$set': {
                'status': 'failed',
                'message': 'Import interrupted by a server restart. Upload the CSV again.',
            }
        },
    )
    from .columns import enrich
    from .hierarchy import decorate

    for dataset_id in db.issues.distinct(
        'dataset_id', {'summary.normalization_version': {'$not': {'$gte': 4}}}
    ):
        docs = list(db.issues.find({'dataset_id': dataset_id}, {'_id': 0}))
        for doc in docs:
            if doc['summary'].get('normalization_version', 1) < 4:
                enrich(doc['summary'], doc['details']['fields'])
        for issue in decorate([doc['summary'] for doc in docs]):
            db.issues.update_one(
                {'dataset_id': dataset_id, 'key': issue['key']}, {'$set': {'summary': issue}}
            )


def create_dataset(
    dataset_id, filename, imported_at, status='queued', message='CSV uploaded; waiting to process'
):
    mongo().datasets.insert_one(
        {
            'id': dataset_id,
            'filename': filename,
            'imported_at': imported_at,
            'status': status,
            'progress': 0,
            'message': message,
            'metadata': {},
        }
    )


def dataset(dataset_id):
    return mongo().datasets.find_one({'id': dataset_id}, {'_id': 0})


def update(dataset_id, status, progress, message, metadata=None):
    changes = {'status': status, 'progress': progress, 'message': message}
    if metadata is not None:
        changes['metadata'] = metadata
    mongo().datasets.update_one({'id': dataset_id}, {'$set': changes})


def issue_document(dataset_id, summary, details):
    return {
        'dataset_id': dataset_id,
        'key': summary['key'],
        'project': summary['project_key'],
        'summary': summary,
        'details': details,
        'sort_recent': recency.rank(summary)[0],
        'sort_created': recency.rank(summary)[1],
        'sort_project': summary['key'].rsplit('-', 1)[0],
        'sort_number': int(summary['key'].rsplit('-', 1)[-1])
        if summary['key'].rsplit('-', 1)[-1].isdigit()
        else 0,
        'exported_fields': [{'name': name, 'values': values} for name, values in details['fields'].items()],
    }


def save_issues(dataset_id, issues):
    operations = []
    for summary, details in issues:
        document = issue_document(dataset_id, summary, details)
        if len(BSON.encode(document)) > 16 * 1024 * 1024 - 1024:
            raise RecordTooLarge(
                'A ticket exceeds MongoDB’s 16 MB record limit. Export fewer large text fields and try again.'
            )
        operations.append(
            ReplaceOne({'dataset_id': dataset_id, 'key': summary['key']}, document, upsert=True)
        )
    if operations:
        mongo().issues.bulk_write(operations, ordered=True)


def issue(dataset_id, key):
    return mongo().issues.find_one({'dataset_id': dataset_id, 'key': key}, {'_id': 0})


def summaries(dataset_id, project=None, extra_match=None):
    query = {'dataset_id': dataset_id}
    if project:
        query['project'] = project
    if extra_match:
        query.update(extra_match)
    return [r['summary'] for r in mongo().issues.find(query, {'summary': 1, '_id': 0})]


def workflows(dataset_id):
    return {r['project']: r['config'] for r in mongo().workflows.find({'dataset_id': dataset_id})}


def save_workflow(dataset_id, project, config):
    save_workflows(dataset_id, {project: config})


def save_workflows(dataset_id, configs):
    operations = [
        ReplaceOne(
            {'dataset_id': dataset_id, 'project': key},
            {'dataset_id': dataset_id, 'project': key, 'config': config},
            upsert=True,
        )
        for key, config in configs.items()
    ]
    if operations:
        mongo().workflows.bulk_write(operations)


def field_rows(dataset_id, project=None):
    query = {'dataset_id': dataset_id}
    if project:
        query['project'] = project
    return {
        r['key']: r['details']['fields'] for r in mongo().issues.find(query, {'key': 1, 'details.fields': 1})
    }


def incoming_issue_links(dataset_id, issue):
    from .references import LINK_FIELDS

    numbers = [
        value for value in (issue.get('issue_id', ''), issue['key'].rsplit('-', 1)[-1]) if value.isdigit()
    ]
    pattern = r'(?<![\w-])' + re.escape(issue['key']) + r'(?![\w-])'
    if numbers:
        pattern += r'|^\s*(?:' + '|'.join(re.escape(value) for value in numbers) + r')\s*$'
    return mongo().issues.aggregate(
        [
            {
                '$match': {
                    'dataset_id': dataset_id,
                    'key': {'$ne': issue['key']},
                    'exported_fields': {
                        '$elemMatch': {
                            'name': {'$regex': LINK_FIELDS, '$options': 'i'},
                            'values': {'$regex': pattern, '$options': 'i'},
                        }
                    },
                }
            },
            {
                '$project': {
                    '_id': 0,
                    'summary': 1,
                    'fields': {
                        '$filter': {
                            'input': '$exported_fields',
                            'as': 'field',
                            'cond': {
                                '$regexMatch': {'input': '$$field.name', 'regex': LINK_FIELDS, 'options': 'i'}
                            },
                        }
                    },
                }
            },
        ]
    )


def people_profiles(dataset_id):
    return {
        (r['project'], r['assignee']): r['profile'] for r in mongo().people.find({'dataset_id': dataset_id})
    }


def save_people(dataset_id, profiles):
    operations = [
        ReplaceOne(
            {'dataset_id': dataset_id, 'project': p['project'], 'assignee': p['assignee']},
            {'dataset_id': dataset_id, 'project': p['project'], 'assignee': p['assignee'], 'profile': p},
            upsert=True,
        )
        for p in profiles
    ]
    if operations:
        mongo().people.bulk_write(operations)


NORMALIZED = {
    'key',
    'summary',
    'assignee',
    'reporter',
    'status',
    'category',
    'priority',
    'type',
    'resolution',
    'sprints',
    'points',
    'project_key',
    'project_name',
    'issue_id',
    'parent_key',
    'created',
    'updated',
    'resolved',
    'original_seconds',
    'remaining_seconds',
    'spent_seconds',
}


def field_expression(dataset_id, field):
    if field in NORMALIZED:
        value = '$summary.' + field
        return {'$cond': [{'$isArray': value}, value, [{'$ifNull': [value, None]}]]}
    if not mongo().issues.find_one({'dataset_id': dataset_id, 'exported_fields.name': field}, {'_id': 1}):
        raise ValueError('Unknown metadata field. Use an exact exported header or normalized field name.')
    return {
        '$reduce': {
            'input': {
                '$filter': {
                    'input': '$exported_fields',
                    'as': 'f',
                    'cond': {'$eq': ['$$f.name', {'$literal': field}]},
                }
            },
            'initialValue': [],
            'in': {'$concatArrays': ['$$value', '$$this.values']},
        }
    }


def filter_expression(dataset_id, item):
    field, op, value = item['field'], item['operator'], item['value']
    values = field_expression(dataset_id, field)
    text = {'$convert': {'input': '$$v', 'to': 'string', 'onError': '', 'onNull': ''}}
    if op == 'empty':
        return {
            '$not': [
                {
                    '$anyElementTrue': {
                        '$map': {'input': values, 'as': 'v', 'in': {'$ne': [{'$trim': {'input': text}}, '']}}
                    }
                }
            ]
        }
    if op in {'gt', 'lt'}:
        try:
            target = float(value)
        except (TypeError, ValueError):
            return {'$literal': False}
        condition = {
            '$and': [
                {
                    '$ne': [
                        {'$convert': {'input': '$$v', 'to': 'double', 'onError': None, 'onNull': None}},
                        None,
                    ]
                },
                {
                    '$' + op: [
                        {'$convert': {'input': '$$v', 'to': 'double', 'onError': None, 'onNull': None}},
                        target,
                    ]
                },
            ]
        }
    else:
        pattern = re.escape(str(value))
        condition = {
            '$regexMatch': {
                'input': text,
                'regex': '^' + pattern + '$' if op == 'eq' else pattern,
                'options': 'i',
            }
        }
    return {'$anyElementTrue': {'$map': {'input': values, 'as': 'v', 'in': condition}}}


def query_metadata(
    dataset_id, project, sprint, filters, group_by, page, limit, allowed_keys=None, include_tickets=True
):
    undated = list(
        mongo().issues.find(
            {'dataset_id': dataset_id, 'sort_recent': {'$exists': False}}, {'key': 1, 'summary': 1}
        )
    )
    if undated:
        mongo().issues.bulk_write(
            [
                UpdateOne(
                    {'_id': row['_id']},
                    {
                        '$set': {
                            'sort_recent': recency.rank(row['summary'])[0],
                            'sort_created': recency.rank(row['summary'])[1],
                        }
                    },
                )
                for row in undated
            ],
            ordered=False,
        )
    match = {'dataset_id': dataset_id}
    if project:
        match['project'] = project
    if sprint:
        match['summary.sprints'] = {'$size': 0} if sprint == '__unscheduled__' else sprint
    if allowed_keys is not None:
        match['key'] = {'$in': allowed_keys}
    normalized = [
        item for item in filters if item['field'] in NORMALIZED and item['operator'] in {'eq', 'contains'}
    ]
    if normalized:
        match['$and'] = [
            {
                'summary.' + item['field']: {
                    '$regex': ('^' if item['operator'] == 'eq' else '')
                    + re.escape(str(item['value']))
                    + ('$' if item['operator'] == 'eq' else ''),
                    '$options': 'i',
                }
            }
            for item in normalized
            if item['field'] not in {'points', 'original_seconds', 'remaining_seconds', 'spent_seconds'}
        ]
        if not match['$and']:
            del match['$and']
    pipeline = [{'$match': match}]
    if filters:
        pipeline.append(
            {'$match': {'$expr': {'$and': [filter_expression(dataset_id, item) for item in filters]}}}
        )
    facets = {
        'count': [{'$count': 'total'}],
        'tickets': (
            [
                {'$sort': {'sort_recent': -1, 'sort_created': -1, 'sort_number': -1, 'key': -1}},
                {'$skip': (page - 1) * limit},
                {'$limit': limit},
                {'$replaceWith': '$summary'},
            ]
            if include_tickets
            else [{'$match': {'_id': {'$exists': False}}}]
        ),
    }
    if group_by:
        values = field_expression(dataset_id, group_by)
        facets['groups'] = [
            {'$project': {'values': {'$setUnion': [values, []]}}},
            {'$unwind': {'path': '$values', 'preserveNullAndEmptyArrays': True}},
            {
                '$group': {
                    '_id': {
                        '$convert': {
                            'input': '$values',
                            'to': 'string',
                            'onError': 'Not provided',
                            'onNull': 'Not provided',
                        }
                    },
                    'count': {'$sum': 1},
                }
            },
            {'$sort': {'count': -1, '_id': 1}},
        ]
    result = next(iter(mongo().issues.aggregate(pipeline + [{'$facet': facets}], maxTimeMS=10000)))
    return {
        'total': result['count'][0]['total'] if result['count'] else 0,
        'tickets': result['tickets'],
        **(
            {'groups': [{'name': row['_id'], 'count': row['count']} for row in result['groups']]}
            if group_by
            else {}
        ),
    }


def find_people(dataset_id, query, project=None):
    match = {'dataset_id': dataset_id}
    if project:
        match['project'] = project
    pipeline = [
        {'$match': match},
        {'$project': {'names': ['$summary.assignee', '$summary.reporter']}},
        {'$unwind': '$names'},
        {
            '$match': {
                '$and': [
                    {'names': {'$regex': re.escape(word), '$options': 'i', '$ne': ''}}
                    for word in query.split()
                ]
                or [{'names': {'$ne': ''}}]
            }
        },
        {'$group': {'_id': '$names'}},
        {'$sort': {'_id': 1}},
    ]
    return [row['_id'] for row in mongo().issues.aggregate(pipeline, maxTimeMS=10000)]


def sprint_status_counts(dataset_id, project=None, allowed_keys=None):
    match = {'dataset_id': dataset_id}
    if project:
        match['project'] = project
    if allowed_keys is not None:
        match['key'] = {'$in': allowed_keys}
    result = next(
        iter(
            mongo().issues.aggregate(
                [
                    {'$match': match},
                    {
                        '$facet': {
                            'unscheduled': [
                                {'$match': {'summary.sprints': {'$size': 0}}},
                                {'$count': 'count'},
                            ],
                            'statuses': [
                                {
                                    '$project': {
                                        'sprints': {'$setUnion': ['$summary.sprints', []]},
                                        'summary': 1,
                                        'project': 1,
                                    }
                                },
                                {'$unwind': '$sprints'},
                                {
                                    '$group': {
                                        '_id': {
                                            'project': '$project',
                                            'sprint': '$sprints',
                                            'status': '$summary.status',
                                            'category': '$summary.category',
                                        },
                                        'count': {'$sum': 1},
                                    }
                                },
                            ],
                        }
                    },
                ],
                maxTimeMS=10000,
            )
        )
    )
    return result['statuses'], result['unscheduled'][0]['count'] if result['unscheduled'] else 0
