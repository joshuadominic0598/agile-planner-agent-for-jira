"""Versioned analysis workflows with evidence-first routing and concise output contracts."""

import re

CATALOG = {'sprint', 'project', 'backlog', 'employee'}


def detailed_readout(prepared):
    """Counts and identities are rendered by code, never reconstructed by a model."""
    data = prepared['facts']
    scope = data['scope']
    total = data['metrics']['total']

    def safe(value):
        return re.sub(r'[\\`*_{}\[\]<>|#]', '', str(value)).replace('\n', ' ')

    title = data.get('person') or (scope['sprint'] if prepared['skill'] == 'sprint' else scope['project'])
    lines = [
        f'## {safe(title)}',
        f'{safe(scope["project"])} · {safe(scope["sprint"])} · CSV snapshot',
        '',
        '| Verified metric | Count |',
        '| --- | ---: |',
    ]
    if 'person' in data:
        lines += [
            f'| Assigned tickets | {data["assigned_tickets"]:,} |',
            f'| Reported tickets | {data["reported_tickets"]:,} |',
            f'| Distinct tickets assigned or reported (union) | {data["participation_unique"]:,} |',
        ]
    else:
        lines += [
            f'| Total tickets | {total:,} |',
            f'| Distinct assignees | {data["people"]["assignees"]:,} |',
            f'| Distinct reporters | {data["people"]["reporters"]:,} |',
        ]
    for heading, key, label in [
        ('Status Category', 'categories', 'label'),
        ('Detailed Status', 'statuses', 'name'),
    ]:
        lines += ['', f'### {heading}', '']
        lines += (
            [f'| {heading} | Tickets | Share of {total:,} tickets |', '| --- | ---: | ---: |']
            if key == 'categories'
            else [f'| {heading} | Tickets |', '| --- | ---: |']
        )
        for row in data[key]:
            share = (
                next(
                    (i['percent'] for i in data['calculated_insights'] if i['name'] == row[label] + ' share'),
                    None,
                )
                if key == 'categories'
                else None
            )
            # Detailed status counts are shown without uncomputed percentages.
            lines.append(
                f'| {safe(row[label])} | {row["count"]:,} |'
                + (f' {str(share) + "%" if share is not None else "—"} |' if key == 'categories' else '')
            )
    lines += [
        '',
        'Status Category and Detailed Status are separate views of the same tickets; do not add them together.',
    ]
    if 'definition' in data:
        lines += [
            '',
            data['definition'],
            f'Unscheduled tickets: **{data["unscheduled"]:,}**. Unclassified category: **{data["unclassified"]:,}**.',
        ]
    lines += ['', '### Coverage', '']
    lines += [
        f'- {safe(i["name"])}: **{i["percent"]}%** ({i["numerator"]:,}/{i["denominator"]:,} tickets).'
        for i in data['calculated_insights']
        if i['percent'] is not None and i['name'] in {'Unassigned share', 'Story-point coverage'}
    ]
    if 'ticket_list' in data:
        lines += [
            '',
            '### Matching tickets',
            '',
            '| Ticket | Title | Priority | Status | Assignee |',
            '| --- | --- | --- | --- | --- |',
        ]
        lines += [
            f'| {safe(i["key"])} | {safe(i["summary"])} | {safe(i["priority"])} | {safe(i["status"])} | {safe(i["assignee"] or "Unassigned")} |'
            for i in data['ticket_list']
        ]
        lines += [
            '',
            f'Showing {data["listed"]} of {total} matching tickets.',
            safe(data['context_description']),
        ]
    lines += ['', data['limitations'], '', '### Analytical observations', '']
    return '\n'.join(lines)


def readout(prepared):
    """A direct answer first; complete report tables are a separate expandable payload."""
    data = prepared['facts']
    kind = prepared['skill']

    def safe(value):
        return re.sub(r'[\\`*_{}\[\]<>|#]', '', str(value)).replace('\n', ' ')

    if kind == 'topics':
        lines = [
            '## Suggested work themes',
            f'**{data["total"]:,} tickets** in the current {"backlog collection" if data.get("collection") else "conversation scope"}.',
            '',
            '| Theme keywords | Tickets | Examples |',
            '| --- | ---: | --- |',
        ]
        lines += [
            f'| {safe(t["name"])} | {t["count"]:,} | {", ".join(safe(e["key"]) for e in t["examples"])} |'
            for t in data['themes']
        ]
        return (
            '\n'.join(lines)
            + '\n\n*Suggested groups from titles/descriptions; every matching ticket is counted once. Labels may need your review.*\n'
        )
    total = data['metrics']['total']
    scope = data['scope']
    title = (
        'Matching tickets'
        if kind == 'tickets'
        else data.get('person') or (scope['sprint'] if kind == 'sprint' else scope['project'])
    )
    lines = [
        f'## {safe(title)}',
        '',
        '| Metric | Count |',
        '| --- | ---: |',
        f'| Total tickets | {total:,} |',
    ]
    if 'person' in data:
        lines += [
            f'| Assigned tickets | {data["assigned_tickets"]:,} |',
            f'| Reported tickets | {data["reported_tickets"]:,} |',
            f'| Distinct tickets assigned or reported (union) | {data["participation_unique"]:,} |',
        ]
    elif kind != 'tickets':
        lines += [
            f'| Distinct assignees | {data["people"]["assignees"]:,} |',
            f'| Distinct reporters | {data["people"]["reporters"]:,} |',
        ]
    if kind == 'tickets':
        lines += ['', '| Ticket | Title | Priority | Status |', '| --- | --- | --- | --- |']
        lines += [
            f'| {safe(i["key"])} | {safe(i["summary"])} | {safe(i["priority"])} | {safe(i["status"])} |'
            for i in data['ticket_list']
        ]
        lines += (
            ['', f'Showing {data["listed"]} of {total:,}; ask for the next page for more.']
            if data['has_more']
            else []
        )
    else:
        lines += ['', '### Status Category', '', '| Category | Tickets |', '| --- | ---: |']
        lines += [f'| {safe(c["label"])} | {c["count"]:,} |' for c in data['categories']]
    if kind == 'backlog':
        lines += [
            '',
            f'**{data["unscheduled"]:,} unscheduled**. Backlog proxy: tickets outside the Done Status Category; CSV board placement is unavailable.',
        ]
    lines += (
        ['', '*CSV snapshot; historical progress and capacity are unavailable.*', '']
        if kind != 'tickets'
        else ['']
    )
    return '\n'.join(lines)


def identify(message, requested=None):
    lower = message.casefold()
    person = ''
    for pattern in (
        r'(?:tell me about|show me|show|analy[sz]e)\s+(.+?)(?:[’\']s)?\s+(?:work(?:\s+items?)?|tickets?|issues?|workload)',
        r"(?:what(?:'s| is))\s+(.+?)\s+working on",
        r'(?:employee|person|assignee)\s+analysis\s+(?:for\s+)?(.+)',
    ):
        match = re.search(pattern, message, re.I)
        if match:
            candidate = match[1].strip().strip("'’")
            if (
                not re.search(r'\d', candidate)
                and candidate.casefold() not in {'this', 'the', 'related', 'my project', 'this project'}
                and len(candidate.split()) <= 5
            ):
                person = candidate
                break
    if requested in CATALOG:
        return requested, person
    if person:
        return 'employee', person
    if 'sprint' in lower and any(w in lower for w in ('summar', 'overview', 'insight', 'status', 'report')):
        return 'sprint', ''
    if 'backlog' in lower:
        return 'backlog', ''
    if any(
        w in lower
        for w in ('project overview', 'overall view', 'project status', 'project summary', 'project health')
    ):
        return 'project', ''
    return '', ''


def prepare(context, message, requested=None):
    if getattr(context, 'comparing_people', False) or getattr(context, 'comparing_values', False):
        return None
    skill, person = identify(message, requested)
    if not skill:
        return None
    context.skill = skill
    context.emit('activity', {'message': f'Using the {skill} analysis workflow.'})
    lower = message.casefold()
    project = '__all__' if re.search(r'all (?:the )?projects|across projects|whole export', lower) else None
    for key in context.projects:
        if re.search(r'\b' + re.escape(key) + r'\b', message, re.I):
            project = key
            break
    if skill == 'employee':
        if (
            re.search(r'\b(?:priority|status|type|category|sprint)\b', person, re.I)
            and not context.find_people(person)['people']
        ):
            return None
        if getattr(context, 'conversation_memory', {}).get('filters') and not getattr(
            context, 'conversation_memory', {}
        ).get('person'):
            return None
        if not person:
            return {
                'clarification': 'Which person would you like to analyze? Enter an exported assignee or reporter name.'
            }
        result = context.call('employee_analysis', {'person': person, 'project': project or '__all__'})
    elif skill == 'sprint':
        match = re.search(r'\bsprint\s*#?\s*(\d+)\b', message, re.I)
        reference = match[1] if match else None
        result = context.call('sprint_summary', {'sprint': reference, 'project': project})
    else:
        result = context.call(
            'backlog_overview' if skill == 'backlog' else 'project_summary', {'project': project}
        )
    if result.get('ambiguous'):
        return {
            'clarification': result['message']
            + '\n\n'
            + '\n'.join(
                '- ' + (i.get('name') or i.get('key') or str(i)) for i in result.get('candidates', [])
            )
        }
    if result.get('not_found') or 'error' in result:
        return {'clarification': result.get('message') or result['error']}
    return {'skill': skill, 'instructions': context.skill_catalog[skill], 'facts': result}
