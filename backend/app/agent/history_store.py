"""MongoDB conversation history with stable numeric cursors and durable memory."""

from pymongo import ReturnDocument

from .. import store


def session(session_id):
    return store.mongo().agent_sessions.find_one({'id': session_id}, {'_id': 0})


def messages(session_id, before_id=None, limit=60):
    query = {'session_id': session_id}
    if before_id:
        query['id'] = {'$lt': before_id}
    rows = list(store.mongo().agent_messages.find(query, {'_id': 0}).sort('id', -1).limit(limit))
    return [
        {'id': r['id'], 'role': r['role'], **r['payload'], 'created_at': r['created_at']}
        for r in reversed(rows)
    ]


def memory(dataset_id, session_id):
    row = store.mongo().agent_session_memory.find_one({'session_id': session_id, 'dataset_id': dataset_id})
    return row['state'] if row else None


def has_older(session_id, before_id):
    return bool(
        before_id
        and store.mongo().agent_messages.find_one(
            {'session_id': session_id, 'id': {'$lt': before_id}}, {'_id': 1}
        )
    )


def list_sessions(dataset_id, offset, limit):
    pipeline = [
        {'$match': {'dataset_id': dataset_id} if dataset_id else {}},
        {'$lookup': {'from': 'datasets', 'localField': 'dataset_id', 'foreignField': 'id', 'as': 'dataset'}},
        {'$unwind': '$dataset'},
        {
            '$lookup': {
                'from': 'agent_messages',
                'let': {'sid': '$id'},
                'pipeline': [
                    {'$match': {'$expr': {'$eq': ['$session_id', '$$sid']}}},
                    {'$sort': {'id': 1}},
                    {
                        '$group': {
                            '_id': None,
                            'last_id': {'$last': '$id'},
                            'updated_at': {'$max': '$created_at'},
                            'preview': {'$last': '$payload.content'},
                            'message_count': {'$sum': 1},
                        }
                    },
                ],
                'as': 'stats',
            }
        },
        {'$unwind': {'path': '$stats', 'preserveNullAndEmptyArrays': True}},
        {'$sort': {'stats.last_id': -1, 'created_at': -1, 'id': 1}},
        {'$skip': offset},
        {'$limit': limit + 1},
    ]
    rows = list(store.mongo().agent_sessions.aggregate(pipeline))
    result = []
    for row in rows[:limit]:
        title = store.mongo().agent_messages.find_one(
            {'session_id': row['id'], 'role': 'user'}, {'payload.content': 1}, sort=[('id', 1)]
        )
        stats = row.get('stats', {})
        result.append(
            {
                'session_id': row['id'],
                'dataset_id': row['dataset_id'],
                'filename': row['dataset']['filename'],
                'title': ((title or {}).get('payload', {}).get('content') or 'New conversation')[:100],
                'preview': (stats.get('preview') or '')[:160],
                'created_at': row['created_at'],
                'updated_at': stats.get('updated_at') or row['created_at'],
                'message_count': stats.get('message_count', 0),
            }
        )
    return {'sessions': result, 'has_more': len(rows) > limit, 'next_offset': offset + min(len(rows), limit)}


def append_messages(session_id, records):
    db = store.mongo()
    counter = db.counters.find_one_and_update(
        {'_id': 'message_id'},
        {'$inc': {'value': len(records)}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    first = counter['value'] - len(records) + 1
    db.agent_messages.insert_many(
        [
            {
                'id': first + n,
                'session_id': session_id,
                'role': role,
                'payload': payload,
                'created_at': created_at,
            }
            for n, (role, payload, created_at) in enumerate(records)
        ]
    )


def save_turn(dataset_id, session_id, project, now, state, user, assistant, preceding_users=()):
    db = store.mongo()
    db.agent_sessions.update_one(
        {'id': session_id},
        {'$setOnInsert': {'id': session_id, 'dataset_id': dataset_id, 'project': project, 'created_at': now}},
        upsert=True,
    )
    append_messages(
        session_id,
        [('user', item, now) for item in preceding_users]
        + [('user', user, now), ('assistant', assistant, now)],
    )
    db.agent_session_memory.update_one(
        {'session_id': session_id},
        {'$set': {'session_id': session_id, 'dataset_id': dataset_id, 'state': state, 'updated_at': now}},
        upsert=True,
    )
