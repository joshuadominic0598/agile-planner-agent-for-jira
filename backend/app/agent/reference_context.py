"""Resolve user-selected tickets and visible lists without guessing from retrieval sources."""

import re

KEY = re.compile(r'\b[A-Za-z][A-Za-z0-9_]*-\d+\b')
ITEM = r'(?:tickets?|ticekts?|issues?|work items?|stor(?:y|ies)|tasks?|bugs?)'


def keys(context, text):
    return list(
        dict.fromkeys(
            context.by_key[key.casefold()]['key']
            for key in KEY.findall(text)
            if key.casefold() in context.by_key
        )
    )


def listed(context, text):
    rows = [
        found
        for line in text.splitlines()
        if re.match(r'^\s*(?:[-*+]\s|\d+[.)]\s|\|)', line) and (found := keys(context, line))
    ]
    return list(dict.fromkeys(key for row in rows for key in row)) if len(rows) > 1 else []


def ownership_question(text):
    return bool(
        re.search(
            r'\b(?:assignees?|owners?|ownership)\b|\bwho\b.*\b(?:handl\w*|assign\w*|own\w*|work\w*|responsible|report\w*)\b',
            text,
            re.I,
        )
    )


def ownership_role(text, previous='assignee'):
    if re.search(r'\breport(?:er|ed|s)?\b', text, re.I):
        return 'both' if re.search(r'\b(?:assignees?|owners?|handles?)\b', text, re.I) else 'reporter'
    return previous if previous in {'assignee', 'reporter', 'both'} else 'assignee'


NEW_TASK = r'\b(?:review|analy[sz]e|assess|triage|compare|classify|explain|describe|summari[sz]e|similar|related|find|priorit\w*|status\w*|points|sprint|search)\b'


def prior_ownership(history):
    for item in reversed(history):
        if item['role'] != 'user':
            continue
        if ownership_question(item['content']):
            return ownership_role(item['content'])
        if re.search(NEW_TASK, item['content'], re.I):
            break
    return None


def elliptical_followup(text):
    allowed = set(
        'okay ok yes and what how about the other others rest these those them all one ones tickets ticekts issues work items mentioned listed above previous response reply answer please too also for from in can could you show check include'.split()
    )
    return all(word in allowed or word.isdigit() for word in re.findall(r"\b[\w']+\b", text.casefold()))


def prepare(context, message, attached=(), history=()):
    if getattr(context, 'references_prepared', False) or not hasattr(context, 'rows'):
        return
    context.references_prepared = True
    context.reference_targets = []
    context.reference_task = ''
    context.ownership_verified = set()
    state = getattr(context, 'conversation_memory', {})
    previous = next((item for item in reversed(history) if item['role'] == 'assistant'), {})
    previous_user = next((item for item in reversed(history) if item['role'] == 'user'), {})
    visible = keys(context, previous.get('content', ''))
    collection = state.get('ticket_set', [])
    if not collection:
        collection = next(
            (
                found
                for item in reversed(history)
                if item['role'] == 'assistant' and len(found := listed(context, item.get('content', ''))) > 1
            ),
            [],
        )
    explicit = list(dict.fromkeys(KEY.findall(message)))
    if not explicit:
        explicit = re.findall(r'\b(?:ticket|issue|work item)\s*#?\s*(\d+)\b', message, re.I)
        if message.strip().isdigit():
            explicit = [message.strip()]
    singular = bool(
        re.search(
            r'\b(?:this|that|same|above|selected|attached|open|current|visible|displayed)\s+(?:jira\s+)?(?:ticket|ticekt|issue|work item|story|task|bug)\b'
            r'|\bthe (?:ticket|issue|work item)\b|\b(?:this|that) one\b'
            r'|\bexplain (?:it|that)\b(?!\s+(?:sprint|project|team|backlog)\b)'
            r'|\b(?:explain|describe|summari[sz]e|analy[sz]e|review|tell me about) (?:it|this|that)\b(?=\s*[.!?]?\s*$)',
            message,
            re.I,
        )
    )
    plural = bool(
        re.search(
            r'\b(?:these|those|them|others|the rest)\b|\btheir (?:assignees|owners|reporters)\b|\b(?:other|above|mentioned|listed)\b.*\b'
            + ITEM
            + r'\b|\b'
            + ITEM
            + r'\b.*\b(?:above|mentioned|listed)\b',
            message,
            re.I,
        )
    )
    previous_role = prior_ownership(history)
    inherited_ownership = bool(
        plural
        and (state.get('ticket_set_intent') == 'ownership' or previous_role is not None)
        and elliptical_followup(message)
    )
    ownership = ownership_question(message) or inherited_ownership
    context.reference_role = ownership_role(
        message,
        (previous_role or state.get('ticket_set_role', 'assignee')) if inherited_ownership else 'assignee',
    )
    pending = state.get('pending_ticket_reference', [])
    if not explicit and not attached and pending:
        ordinal = re.fullmatch(
            r'(?:the )?(first|second|third|fourth|last)(?: one| ticket| issue)?[.!]?', message.strip(), re.I
        )
        options = [key for key in visible if key in pending]
        if ordinal and options:
            position = {'first': 0, 'second': 1, 'third': 2, 'fourth': 3, 'last': -1}[ordinal[1].casefold()]
            if -len(options) <= position < len(options):
                explicit = [options[position]]
        phrase = re.sub(
            r'^(?:the one about|the ticket about|the issue about)\s+', '', message.strip(' .?!'), flags=re.I
        ).casefold()
        matches = [
            key
            for key in pending
            if key.casefold() in context.by_key
            and len(phrase) >= 4
            and (
                phrase in context.by_key[key.casefold()]['summary'].casefold()
                or context.by_key[key.casefold()]['summary'].casefold() in phrase
            )
        ]
        if len(matches) == 1:
            explicit = matches
    refs = explicit or list(dict.fromkeys(attached))
    page_ticket = getattr(context, 'page_ticket', '')
    page_selected = False
    if (
        not refs
        and singular
        and page_ticket
        and re.search(
            r'\b(?:this|open|current|selected|visible|displayed)\s+(?:jira\s+)?(?:ticket|issue|work item|story|task|bug|one)\b',
            message,
            re.I,
        )
    ):
        refs, page_selected = [page_ticket], True
    if (
        not refs
        and plural
        and (ownership or not getattr(context, 'context_lookup', False))
        and not re.search(r'\b(?:similar|related|search)\b', message, re.I)
    ):
        refs = collection or visible
    if not refs and singular:
        prior_refs = keys(context, previous_user.get('content', '')) or previous_user.get('attachments', [])
        focus = state.get('tickets', []) if state.get('focus') == 'ticket' else []
        if len(prior_refs) == 1:
            refs = prior_refs
        elif len(visible) <= 1 and len(focus) == 1 and (not visible or visible == focus):
            refs = focus
        elif page_ticket:
            refs, page_selected = [page_ticket], True
    if singular and not explicit and len(refs) != 1:
        candidates = refs or visible or collection
        state['pending_ticket_reference'] = candidates[:8]
        state.update(tickets=[], focus='ticket_selection', topic='')
        context.reference_clarification = True
        context.topic_query = ''
        context.context_lookup = False
        context.memory_clarification = (
            'Which ticket do you mean? Share its key/title or attach it from the ticket details.'
        )
        context.emit('activity', {'message': 'Waiting for a ticket selection before retrieving details.'})
        if candidates:
            context.memory_clarification += '\nRecently discussed options:\n' + '\n'.join(
                '- ' + key + ' — ' + context.by_key[key.casefold()]['summary']
                for key in candidates[:4]
                if key.casefold() in context.by_key
            )
        return
    if refs:
        state['pending_ticket_reference'] = []
        refs = [
            context.by_key[ref.casefold()]['key'] if ref.casefold() in context.by_key else ref for ref in refs
        ]
        if ownership:
            resolved = [context.resolve(ref) for ref in refs]
            missing = next((item for item in resolved if 'ticket' not in item), None)
            if missing:
                context.reference_clarification = True
                context.memory_clarification = missing.get('message', 'Which ticket keys do you mean?')
                return
            refs = [item['ticket']['key'] for item in resolved]
        context.reference_targets = refs[:40]
        context.topic_query = ''
        context.context_lookup = False
        if ownership:
            context.reference_task = 'ownership'
            state['ticket_set_role'] = context.reference_role
            state['ticket_set_intent'] = 'ownership'
            state['ticket_set'] = context.reference_targets
        elif len(refs) == 1:
            state.update(tickets=refs, focus='ticket')
            if explicit or attached or page_selected:
                state.update(person=None, filters=[], topic='', ticket_set=[], ticket_set_intent='')
                context.context_filters = []
        if page_selected:
            state.update(
                tickets=refs,
                focus='ticket',
                person=None,
                filters=[],
                topic='',
                project=None,
                sprint=None,
                collection=None,
                candidates=[],
                unresolved_person=None,
            )
            context.context_filters = []
            context.memory_inherited = False
            context.memory_clarification = ''
            context.clarification_needed = False
    if plural and not refs and ownership:
        context.reference_clarification = True
        context.memory_clarification = (
            'Which tickets should I check? Share their keys, attach them, or specify the group you mean.'
        )


def remember(context, message, answer):
    state = context.conversation_memory
    if getattr(context, 'reference_clarification', False):
        return
    if getattr(context, 'reference_task', '') == 'ownership':
        state['ticket_set'] = context.reference_targets
        state['ticket_set_intent'] = 'ownership'
        return
    visible = [key for key in listed(context, answer) if key in context.citations]
    if len(visible) > 1:
        state['ticket_set'] = visible[:40]
        state['ticket_set_intent'] = 'ownership' if ownership_question(message) else ''
        state['ticket_set_role'] = getattr(context, 'reference_role', ownership_role(message))
    elif getattr(context, 'explicit_references', False):
        state['ticket_set'] = []
        state['ticket_set_intent'] = ''
