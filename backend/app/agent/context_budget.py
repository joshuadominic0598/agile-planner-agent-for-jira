"""Conservative model-aware prompt budgets; durable scope memory is never truncated."""

import copy
import json
import math


class ContextBudgetError(ValueError):
    pass


def settings(cfg):
    model = cfg.get('model', '')
    profile = cfg.get('context_profile', 'auto')
    window = int(cfg.get('model_context_windows', {}).get(model, cfg.get('context_window', 32768)))
    if profile == 'auto':
        profile = cfg.get('model_context_profiles', {}).get(
            model, 'expanded' if window >= 40960 else 'compact'
        )
    window = max(2048, window)
    expanded = profile == 'expanded' and window >= 32768
    if window <= 16384:
        profile = 'compact'
    return {
        'profile': profile,
        'window': window,
        'output_reserve': min(4096, max(512, window // 5)),
        'ticket_initial': 10 if window < 8192 else 30,
        'ticket_max': 10 if window < 8192 else 100 if window >= 32768 else 30,
        'ticket_preferred_min': 20 if window >= 32768 else 1,
        'history_tokens': 1500 if window <= 16384 else 14000 if expanded else 6000,
        'history_messages': 32 if expanded else 12,
        'message_chars': 7000 if expanded else 3500,
        'evidence_chars': 6000 if window <= 16384 else 48000 if expanded else 20000,
        'excerpt_chars': 6000 if expanded else 2000,
        'tool_chars': min(60000, max(1600, int(window * (0.55 if window < 8192 else 1.3)))),
    }


def estimate(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return math.ceil(len(text.encode('utf8')) / 3) + 8


def history(history, cfg, anchors, instructions, tools, context):
    limits = settings(cfg)
    available = max(
        0,
        min(
            limits['history_tokens'],
            int(limits['window'] * 0.9)
            - limits['output_reserve']
            - estimate(anchors)
            - estimate(instructions)
            - estimate(tools),
        ),
    )
    groups = []
    for turn in history:
        if turn['role'] not in {'user', 'assistant'}:
            continue
        content = turn['content'][: limits['message_chars']]
        if turn.get('attachments'):
            content += '\nPreviously attached ticket keys: ' + ', '.join(turn['attachments'][:8])
        if turn['role'] == 'user' or not groups:
            groups.append([])
        groups[-1].append({'role': turn['role'], 'content': content})
    chosen = []
    used = 0
    for group in reversed(groups):
        cost = estimate(group)
        if used + cost > available or len(chosen) + len(group) > limits['history_messages']:
            break
        chosen = group + chosen
        used += cost
    context.context_usage = {
        'profile': limits['profile'],
        'context_window': limits['window'],
        'history_messages': len(chosen),
        'history_messages_available': len(history),
        'history_token_estimate': used,
        'estimator': 'UTF-8 bytes / 3 plus overhead; approximate, not provider tokenization',
        'omitted_tool_rounds': 0,
    }
    context._history_count = len(chosen)
    return chosen


def notice(context, message):
    if context is not None and hasattr(context, 'emit') and not getattr(context, '_budget_notice', False):
        context._budget_notice = True
        context.emit('activity', {'message': message})


def bound_result(value, cfg, context=None, max_chars=None):
    limits = settings(cfg)
    limit = max_chars or limits['tool_chars']
    cap = original_cap = limits['ticket_max']
    string_size, list_size = 1200 if limits['window'] >= 32768 else 500, 500
    selected = set()
    row_fields = {
        'key',
        'summary',
        'description',
        'assignee',
        'reporter',
        'status',
        'category',
        'priority',
        'type',
        'points',
        'created',
        'updated',
        'parent_key',
        'project_key',
        'sprints',
        'retrieval',
        'excerpt',
        'quote',
        'assessment',
        'narrative_excerpt',
        'readiness',
        'estimates',
        'estimate',
        'estimate_counted',
        'priority_finalized',
        'next_step',
        'score',
        'id',
    }

    def clip(item, depth=0):
        if isinstance(item, str):
            return item[:string_size]
        if isinstance(item, list):
            output = []
            ticket_list = any(
                isinstance(child, dict) and 'key' in child and ('summary' in child or 'status' in child)
                for child in item[:2]
            )
            for child in item if ticket_list else item[:list_size]:
                ticket = (
                    isinstance(child, dict)
                    and isinstance(child.get('key'), str)
                    and ('summary' in child or 'status' in child)
                )
                if ticket:
                    if child['key'] not in selected and len(selected) >= cap:
                        continue
                    selected.add(child['key'])
                    child = {key: val for key, val in child.items() if key in row_fields}
                output.append(clip(child, depth + 1))
            return output
        if isinstance(item, dict):
            return {key: clip(val, depth + 1) for key, val in list(item.items())[:100]}
        return item

    def packed():
        selected.clear()
        result = clip(value)
        changed = result != value
        if isinstance(result, dict):
            if isinstance(result.get('example_coverage'), dict) and isinstance(
                result.get('example_tickets'), list
            ):
                result['example_coverage']['shown'] = len(result['example_tickets'])
            if isinstance(result.get('ticket_sampling'), dict) and isinstance(result.get('tickets'), list):
                result['ticket_sampling']['shown'] = len(result['tickets'])
            if isinstance(value, dict):
                coverage = {
                    key: {'shown': len(result.get(key, [])), 'available': len(items)}
                    for key, items in value.items()
                    if isinstance(items, list)
                    and isinstance(result.get(key), list)
                    and len(result[key]) < len(items)
                }
                if coverage:
                    result['list_coverage'] = coverage
        if changed:
            annotation = 'Evidence excerpt optimised for the configured context. Ticket rows favour recent results; full-scope counts remain authoritative. Omitted text is unavailable in this excerpt, not absent from Jira. Query a narrower field or another page if needed.'
            if isinstance(result, dict):
                result['context_excerpt_note'] = annotation
            else:
                result = {'excerpt': result, 'context_excerpt_note': annotation}
        return result

    result = packed()
    while len(json.dumps(result, ensure_ascii=False).encode()) > limit:
        if string_size > 80:
            string_size = max(80, string_size // 2)
        elif cap > limits['ticket_preferred_min']:
            cap = max(limits['ticket_preferred_min'], cap // 2)
        elif list_size > 8:
            list_size = max(8, list_size // 2)
        elif cap > 1:
            cap = max(1, cap // 2)
        else:
            minimal = {
                key: value[key]
                for key in ('total', 'assigned_tickets', 'scope')
                if isinstance(value, dict) and key in value
            }
            minimal['context_excerpt_note'] = (
                'Evidence is too large for this packet. Use a narrower metadata query or fetch one ticket; do not infer missing details.'
            )
            rows = value.get('tickets') or value.get('example_tickets') if isinstance(value, dict) else []
            if rows:
                minimal['tickets'] = [{key: rows[0].get(key) for key in ('key', 'summary', 'status')}]
                minimal['tickets'][0]['summary'] = str(minimal['tickets'][0]['summary'])[:100]
            result = minimal
            break
        result = packed()
    if cap < original_cap and 'context_excerpt_note' in result:
        low, high, best = cap, original_cap, result
        while low < high:
            candidate = (low + high + 1) // 2
            cap = candidate
            packet = packed()
            if len(json.dumps(packet, ensure_ascii=False).encode()) <= limit:
                low, best = candidate, packet
            else:
                high = candidate - 1
        result = best
    if result != value and len(json.dumps(value, ensure_ascii=False).encode()) > limit:
        notice(
            context,
            'Retrieved context is too large; optimising recent ticket excerpts before sending the request.',
        )
    return json.dumps(result, ensure_ascii=False)


def slim_tools(tools, context):
    question = getattr(context, 'current_question', '').casefold()
    memory = getattr(context, 'conversation_memory', {})
    if getattr(context, 'planning_keys', None) is not None:
        preferred = ['record_backlog_plan', 'get_ticket', 'calculator']
    elif getattr(context, 'reference_task', '') == 'ownership':
        preferred = ['ticket_ownership', 'get_ticket', 'query_metadata', 'calculator']
    elif any(term in question for term in ('capacity', 'free', 'available', 'headroom')):
        preferred = ['get_backlog_report', 'capacity_analysis', 'get_project_context', 'calculator']
    elif memory.get('person') or any(
        term in question for term in ('employee', 'work on', 'works on', 'working on', 'person', 'assignee')
    ):
        preferred = ['find_people', 'employee_analysis', 'query_metadata', 'calculator', 'get_ticket']
    elif getattr(context, 'retrieval_route', '') in {'semantic', 'hybrid'}:
        preferred = ['investigate_tickets', 'search_tickets', 'get_ticket', 'query_metadata', 'calculator']
    elif 'sprint' in question:
        preferred = [
            'sprint_summary',
            'query_metadata',
            'sprint_remaining_work',
            'calculator',
            'discover_context',
        ]
    else:
        preferred = [
            'query_metadata',
            'find_people',
            'get_ticket',
            'project_summary',
            'calculator',
            'discover_context',
        ]

    def names(tool):
        return tool.get('name') or tool.get('function', {}).get('name')

    ordered = sorted(
        tools, key=lambda tool: preferred.index(names(tool)) if names(tool) in preferred else len(preferred)
    )
    chosen = ordered[:4]

    def compact(item):
        if isinstance(item, dict):
            return {key: compact(value) for key, value in item.items() if key != 'description'}
        return [compact(value) for value in item] if isinstance(item, list) else item

    return [compact(tool) for tool in chosen]


def fit(body, cfg, context):
    """Drop complete old dialogue/tool rounds, retaining current request and memory."""
    body = copy.deepcopy(body)
    limits = settings(cfg)
    for field in ('max_tokens', 'max_output_tokens'):
        if field in body:
            body[field] = min(body[field], limits['output_reserve'])
    key = 'input' if 'input' in body else 'messages'
    items = list(body[key])
    original_size = estimate(body)
    limit = int(limits['window'] * 0.9) - limits['output_reserve']
    if original_size > limit:
        notice(
            context,
            'Retrieved context is too large; optimising recent ticket excerpts before sending the request.',
        )
    from .. import recency

    packets, records = [], {}
    for item in items:
        field = 'output' if item.get('type') == 'function_call_output' else 'content'
        text = item.get(field)
        if not isinstance(text, str) or not (
            item.get('role') == 'tool'
            or item.get('type') == 'function_call_output'
            or text.startswith('Application-retrieved')
            or text.startswith('Application-computed')
        ):
            continue
        start = min((pos for token in ('{', '[') if (pos := text.find(token)) >= 0), default=-1)
        if start < 0:
            continue
        try:
            data = json.loads(text[start:])
        except ValueError:
            continue
        packets.append((item, field, text[:start], data))

        def collect(value):
            if isinstance(value, list):
                for row in value:
                    if (
                        isinstance(row, dict)
                        and isinstance(row.get('key'), str)
                        and ('summary' in row or 'status' in row)
                    ):
                        records[row['key']] = {**records.get(row['key'], {}), **row}
                    collect(row)
            elif isinstance(value, dict):
                for child in value.values():
                    collect(child)

        collect(data)
    if len(records) > limits['ticket_max']:
        allowed = {row['key'] for row in recency.latest(records.values(), limits['ticket_max'])}

        def retain(value):
            if isinstance(value, list):
                return [
                    retain(row)
                    for row in value
                    if not (isinstance(row, dict) and 'key' in row and ('summary' in row or 'status' in row))
                    or row['key'] in allowed
                ]
            return {key: retain(child) for key, child in value.items()} if isinstance(value, dict) else value

        for item, field, prefix, data in packets:
            item[field] = prefix + bound_result(retain(data), cfg, context)
        notice(
            context,
            f'Retrieved context includes {len(records)} tickets; optimising to the latest {limits["ticket_max"]} for this model window.',
        )

    def size():
        return estimate({**body, key: items})

    if size() > limit and getattr(context, 'feature_evidence', None):
        if 'instructions' in body:
            body['instructions'] = context.compact_instructions
        elif items and items[0].get('role') == 'system':
            items[0]['content'] = context.compact_instructions
        if body.get('tools'):
            body['tools'] = slim_tools(body['tools'], context)
    head = 1 if items and items[0].get('role') == 'system' else 0
    count = getattr(context, '_history_count', 0)
    while count and size() > limit:
        end = head + 1
        while end < head + count and items[end].get('role') != 'user':
            end += 1
        removed = end - head
        del items[head:end]
        count -= removed

    def native(item):
        return (
            item.get('type') in {'reasoning', 'function_call'}
            or item.get('role') == 'assistant'
            and bool(item.get('tool_calls'))
        )

    first = next((n for n, i in enumerate(items) if native(i)), len(items))
    base = items[:first]
    rounds = []
    current = []
    seen_result = False
    for item in items[first:]:
        is_result = item.get('role') == 'tool' or item.get('type') == 'function_call_output'
        if seen_result and not is_result:
            rounds.append(current)
            current = []
            seen_result = False
        current.append(item)
        seen_result |= is_result
    if current:
        rounds.append(current)
    omitted = 0
    while len(rounds) > 1 and size() > limit:
        rounds.pop(0)
        omitted += 1
        omission_notice = {
            'role': 'user',
            'content': 'Earlier tool rounds were omitted to fit the model context. Resolved conversation memory remains authoritative for scope. Fetch omitted detail again if needed.',
        }
        items = base + [omission_notice] + [i for r in rounds for i in r]
    if hasattr(context, 'context_usage'):
        context.context_usage.update(
            request_token_estimate=size(),
            omitted_tool_rounds=max(context.context_usage['omitted_tool_rounds'], omitted),
        )
    if size() > limit:
        notice(
            context,
            'Retrieved context is too large; optimising recent ticket excerpts before sending the request.',
        )
        prefixes = (
            'Application-retrieved ticket evidence',
            'Application-computed analysis evidence',
            'Owner-provided project context',
            'Application navigation hints',
        )
        for budget in (12000, 6000, 3000, 1500, 800):
            for item in items:
                field = 'output' if item.get('type') == 'function_call_output' else 'content'
                content = item.get(field)
                if not isinstance(content, str):
                    continue
                prefix = next((prefix for prefix in prefixes if content.startswith(prefix)), None)
                tool = item.get('role') == 'tool' or item.get('type') == 'function_call_output'
                if not tool and not prefix:
                    continue
                start = min((pos for token in ('{', '[') if (pos := content.find(token)) >= 0), default=-1)
                if start < 0:
                    continue
                try:
                    data = json.loads(content[start:])
                except ValueError:
                    continue
                item[field] = content[:start] + bound_result(data, cfg, context, budget)
            if size() <= limit:
                break
    if size() > limit and body.get('tools'):
        body['tools'] = slim_tools(body['tools'], context)
    if size() > limit and getattr(context, 'compact_instructions', ''):
        if 'instructions' in body:
            body['instructions'] = context.compact_instructions
        elif items and items[0].get('role') == 'system':
            items[0]['content'] = context.compact_instructions
    while size() > limit and len(body.get('tools', [])) > 1:
        body['tools'].pop()
    if size() > limit:
        raise ContextBudgetError(
            'Your question and required conversation scope exceed this context window even after evidence optimisation. Shorten the question or adjust the configured window.'
        )
    if not getattr(context, '_budget_sent', False) and (
        size() < original_size and original_size > limit or getattr(context, '_budget_notice', False)
    ):
        context._budget_sent = True
        if hasattr(context, 'emit'):
            context.emit(
                'activity',
                {
                    'message': f'Sending optimised context: approximately {size():,} input tokens within the configured {limits["window"]:,}-token window.'
                },
            )
    if hasattr(context, 'context_usage'):
        context.context_usage.update(request_token_estimate=size(), context_optimised=original_size > limit)
    return {**body, key: items}
