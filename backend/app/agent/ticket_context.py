"""Bounded ticket evidence, with explicit gaps for external files and missing exports."""

import copy
import json
import re
from urllib.parse import unquote, urlsplit

from .. import columns, references

LINK_FIELDS = references.LINK_FIELDS
CRITERIA = re.compile(r'acceptance\s+(?:criteria|criterion|tests?)|definition\s+of\s+done', re.I)
ATTACHMENT = re.compile(r'^(?:custom field \()?attachments?(?:\))?$', re.I)


def short(issue):
    return {key: issue.get(key, '')[:180] for key in ('key', 'summary', 'status', 'type')}


def tokens(value):
    found = references.KEY.findall(value)
    if value.strip().isdigit():
        found.append(value.strip())
    return list(dict.fromkeys(found))


def attachments(fields):
    files, names = {}, set()
    for name, values in fields.items():
        if not ATTACHMENT.fullmatch(columns.header_key(name)):
            continue
        for value in values:
            if not value.strip():
                continue
            parts = value.rsplit(';', 1)[0].split(';', 2)
            filename = parts[2].strip() if len(parts) == 3 else value.strip()
            if re.match(r'https?://', filename, re.I):
                filename = unquote(urlsplit(filename).path.rsplit('/', 1)[-1]) or 'Unnamed attachment'
            names.add(filename)
            files[(filename, value)] = {'name': filename[:256], 'field': name[:100], 'listed_in_export': True}
    for name in columns.matching_fields(fields, 'description'):
        for value in fields[name]:
            inline = re.findall(r'\[\^([^\]\r\n]+)\]|!([^!|\r\n]+)(?:\|[^!\r\n]*)?!', value)
            for file_ref, image_ref in inline:
                filename = (file_ref or image_ref).strip()
                if not filename or re.match(r'https?://', filename, re.I):
                    continue
                if filename not in names:
                    files.setdefault(
                        (filename, 'inline'),
                        {'name': filename[:256], 'field': name, 'listed_in_export': False},
                    )
    return {
        'count': len(files),
        'items': list(files.values())[:10],
        'truncated': len(files) > 10,
        'contents_available': False,
        'note': 'Only exported filenames/references are available. File contents and images have not been opened or verified. Ask the user to check relevant attachments in Jira; never infer their contents from filenames.',
    }


def criteria(fields):
    items, budget, total, truncated = [], 2400, 0, False
    for name, values in fields.items():
        for value in values:
            if not value.strip():
                continue
            text = value.strip() if CRITERIA.search(name) else ''
            if not text and name in columns.matching_fields(fields, 'description'):
                match = re.search(
                    r'(?im)^[ \t]*(?:h[1-6]\.[ \t]*|#{1,6}[ \t]*|\*{1,2})?(?:'
                    + CRITERIA.pattern
                    + r')[ \t]*[:*\r\n]',
                    value,
                )
                if match:
                    tail = value[match.start() :]
                    text = re.split(r'(?m)\n\s*(?:h[1-6]\.\s|#{1,6}\s)', tail, maxsplit=1)[0].strip()
            if not text:
                continue
            total += 1
            if budget > 0 and len(items) < 6:
                excerpt = text[: min(1000, budget)]
                items.append({'field': name[:100], 'text': excerpt})
                budget -= len(excerpt)
                truncated |= excerpt != text
            else:
                truncated = True
    return {
        'count': total,
        'items': items,
        'truncated': truncated,
        'note': 'Explicitly labeled criteria only. Requirements may also be embedded elsewhere or in unread attachments. Absence here does not prove the ticket has no acceptance requirements.',
    }


def relationships(issue, fields, rows, incoming):
    lookup = references.Index(rows)
    parent = lookup.keys.get(issue.get('parent_key', '').casefold())
    parent_info = short(parent) if parent else None
    if not parent_info and issue.get('has_parent'):
        parent_info = {
            'reference': issue.get('parent_reference', '')[:100],
            'summary': issue.get('parent_title', '')[:180],
            'available_in_export': False,
            'reason': issue.get('parent_reference_problem') or 'not_in_export',
        }
    children = [short(row) for row in rows if row.get('parent_key') == issue['key']]
    links = {}

    def add(source, source_fields, incoming=False):
        for name, values in source_fields.items():
            if not references.reference_field(name) or not re.search(LINK_FIELDS, name, re.I):
                continue
            for value in values:
                for token in tokens(value):
                    target, reason = lookup.resolve(token, source['project_key'])
                    if incoming and (not target or target['key'] != issue['key']):
                        continue
                    if not incoming and target and target['key'] == issue['key']:
                        continue
                    direction = 'incoming' if name.casefold().startswith('inward') else 'outgoing'
                    if incoming:
                        direction = 'outgoing' if direction == 'incoming' else 'incoming'
                    other = source if incoming else target
                    item = short(other) if other else {'reference': token, 'unresolved': reason}
                    item.update(relation=name[:120], direction=direction, exported_on=source['key'])
                    links[(item.get('key', token), name, direction)] = item

    add(issue, fields)
    for record in incoming:
        add(record['summary'], {field['name']: field['values'] for field in record['fields']}, True)
    return {
        'parent': parent_info,
        'parent_warning': issue.get('hierarchy_warning', ''),
        'children_count': len(children),
        'children': children[:10],
        'children_truncated': len(children) > 10,
        'links_count': len(links),
        'links': list(links.values())[:10],
        'links_truncated': len(links) > 10,
        'note': 'Explicit exported relationships only; shared labels or semantic similarity are not dependencies. Missing/ambiguous references are not resolved tickets. Fetch related ticket details when they affect the answer.',
    }


def build(issue, fields, rows, incoming):
    comments = [
        (name, value)
        for name, values in fields.items()
        if name in columns.matching_fields(fields, 'comments')
        for value in values
        if value.strip()
    ]
    return {
        'attachments': attachments(fields),
        'acceptance_criteria': criteria(fields),
        'related_work': relationships(issue, fields, rows, incoming),
        'comments': {
            'count': len(comments),
            'items': [{'field': name[:100], 'text': value[:600]} for name, value in comments[-3:]],
            'truncated': len(comments) > 3 or any(len(value) > 600 for _, value in comments[-3:]),
            'note': 'Last populated CSV occurrences, not necessarily chronological. Comments report claims; they do not independently verify deployments, testing or completion.',
        },
    }


def excerpt(packet, budget):
    result = copy.deepcopy(packet)
    for limit in (4, 2, 1, 0):
        if len(json.dumps(result)) <= budget:
            break
        for section in result.values():
            for name in ('items', 'children', 'links'):
                if isinstance(section.get(name), list) and len(section[name]) > limit:
                    section[name] = section[name][:limit]
                    section['context_excerpt_truncated'] = True
    return result
