"""Deterministic retrieval diagnostics, deliberately labeled separately from an AI answer."""

import re

from . import conversation, reference_context, skills


def run(context, message, attached):
    reference_context.prepare(context, message, attached)
    lower = message.casefold()
    intro = '*Local retrieval preview · verified CSV evidence.*\n\n'
    if getattr(context, 'reference_task', '') == 'ownership':
        data = context.call('ticket_ownership', {'references': context.reference_targets, 'project': None})
        role = getattr(context, 'reference_role', 'assignee')
        return intro + '\n'.join(
            '- '
            + item['key']
            + ' — '
            + item['summary']
            + ': '
            + (
                (item['reporter'] or 'Reporter not provided')
                if role == 'reporter'
                else (item['assignee'] or 'Unassigned')
            )
            for item in data.get('tickets', [])
        )
    prepared = conversation.prepared(context, message) or skills.prepare(
        context, message, getattr(context, 'requested_skill', None)
    )
    if prepared and prepared.get('clarification'):
        return intro + prepared['clarification']
    if prepared:
        if prepared['skill'] not in {'topics', 'tickets'}:
            context.details_markdown = skills.detailed_readout(prepared).split('### Analytical observations')[
                0
            ]
        return intro + skills.readout(prepared)
    expression = re.fullmatch(r'\s*(?:calculate\s+)?([\d\s.+*/%()\-]+)\s*', message, re.I)
    if expression and any(c in expression[1] for c in '+*/%'):
        result = context.call('calculator', {'expression': expression[1]})
        return intro + (result.get('error') or f'{result["expression"]} = {result["result"]}')
    if (
        any(
            word in lower
            for word in ('summar', 'how many', 'overview', 'project status', 'sprint status', 'insight')
        )
        and not attached
    ):
        sprint = 'sprint' in lower
        explicit = [s for i in context.rows for s in i['sprints'] if s.casefold() in lower]
        args = {'sprint': max(explicit, key=len) if explicit else None} if sprint else {}
        data = context.call('sprint_summary' if sprint else 'project_summary', args)
        if 'error' in data:
            return intro + data['error']
        categories = ', '.join(f'{i["label"]}: {i["count"]:,}' for i in data['categories'])
        statuses = ', '.join(f'{i["name"]}: {i["count"]:,}' for i in data['statuses'])
        return (
            intro
            + f'{data["scope"]["project"]} · {data["scope"]["sprint"]}\nTotal tickets: {data["metrics"]["total"]:,}\nStatus categories: {categories or "Not provided"}\nDetailed statuses: {statuses}\nDistinct assignees: {data["people"]["assignees"]}\nDistinct reporters: {data["people"]["reporters"]}\n\nThese are exact snapshot counts, not sprint activity history. Connect a model for a reasoned summary and recommendations.'
        )
    refs = getattr(context, 'reference_targets', []) or list(
        dict.fromkeys([*attached, *re.findall(r'\b[A-Za-z][A-Za-z0-9_]*-\d+\b', message)])
    )
    if not refs:
        numbers = re.findall(r'\b\d+\b', message)
        if len(numbers) == 1:
            refs = numbers
    blocks = []
    for reference in refs[:8]:
        data = context.call('get_ticket', {'reference': reference})
        if data.get('ambiguous'):
            blocks.append(
                'Which ticket did you mean?\n'
                + '\n'.join(f'{i["key"]} — {i["summary"]}' for i in data['candidates'])
            )
            continue
        if 'ticket' not in data:
            blocks.append(data.get('error') or data.get('message', 'Ticket unavailable.'))
            continue
        issue = data['ticket']
        blocks.append(
            f'{issue["key"]} — {issue["summary"]}\n{issue["type"]} · {issue["status"]} · {issue["priority"] or "Priority not provided"}\n'
            + data['source_text'][:2600]
        )
        graph = context.call('explore_graph', {'reference': issue['key'], 'keyword': None, 'depth': 2})
        if graph.get('tickets'):
            blocks.append(
                'Connected through exported relationships:\n'
                + '\n'.join(
                    f'{i["key"]} — {i["summary"]} ({" → ".join(p["relation"] for p in i["path"])})'
                    for i in graph['tickets'][:8]
                )
            )
        if any(w in lower for w in ('similar', 'related', 'like')):
            context.call('search_tickets', {'query': issue['summary'], 'sprint': '__all__', 'limit': 6})
    if refs:
        return intro + '\n\n'.join(blocks)
    result = context.call('search_tickets', {'query': message[:1200], 'sprint': None, 'limit': 6})
    if 'error' in result:
        return intro + result['error']
    for issue in result['tickets']:
        blocks.append(
            f'{issue["key"]} — {issue["summary"]}\n{issue["status"]} · {issue["type"]}\n{issue["excerpt"][:650]}'
        )
    graph = context.call('explore_graph', {'reference': None, 'keyword': message[:1200], 'depth': 2})
    related = [i for i in graph.get('tickets', []) if i['key'] not in {r['key'] for r in result['tickets']}]
    if related:
        blocks.append(
            'Graph connections (may cross sprints):\n'
            + '\n'.join(f'{i["key"]} — {i["summary"]}' for i in related[:6])
        )
    return intro + (
        '\n\n'.join(blocks)
        if blocks
        else 'No matching ticket context found in this scope. Try a ticket key, number or more specific topic. People, statuses and other metadata are queried separately from title/description search.'
    )
