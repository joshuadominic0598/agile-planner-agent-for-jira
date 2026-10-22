"""Explicit CSV contract for expected answers, reference evidence and captured model outputs."""

import csv
import io
import json
import re

from .evaluation_datasets import GoldenCase


def chunks(value):
    if isinstance(value, list):
        return value
    value = str(value or '').strip()
    if not value:
        return []
    if value.startswith('['):
        decoded = json.loads(value)
        if not isinstance(decoded, list) or any(not isinstance(x, str) for x in decoded):
            raise ValueError('Context fields must be JSON arrays of strings or quoted text.')
        return decoded
    return value.split('|||')


def boolean(value):
    if isinstance(value, bool):
        return value
    if str(value or '').casefold() not in {'', 'true', 'false', '1', '0', 'yes', 'no'}:
        raise ValueError('Boolean fields use true/false or 1/0.')
    return str(value).casefold() in {'true', '1', 'yes'}


def convert(row):
    r = {re.sub(r'[\s-]+', '_', k.strip().casefold()): v for k, v in row.items()}

    def first(*names):
        return next((r[n] for n in names if r.get(n) not in (None, '')), '')

    reference = first('reference_answer', 'reference', 'ground_truth', 'expected_answer')
    candidate = first('answer', 'response', 'provided_answer')
    actual = chunks(
        first('retrieved_contexts', 'contexts', 'retrieved_context', 'context', 'provided_contexts')
    )
    expected_contexts = chunks(first('reference_contexts', 'ground_truth_contexts'))
    values = dict(row)
    values.update(
        question=first('question', 'user_input'),
        reference=reference or candidate,
        reference_contexts=expected_contexts or (actual if not reference else []),
        provided_answer=candidate if reference and candidate else None,
        provided_contexts=actual if reference else [],
        reference_status=first('reference_status') or 'needs_human_verification',
        context_status=first('context_status')
        or ('needs_human_verification' if expected_contexts or not reference and actual else 'missing'),
        context_source=first('context_source') or 'User-uploaded evidence; verify against the source export.',
        conversation_id=first('conversation_id') or 'conversation-1',
    )
    if not values.get('id'):
        values.pop('id', None)
    if 'enabled' in r:
        values['enabled'] = boolean(r['enabled'])
    if 'expected' not in values:
        values['expected'] = {
            'clarification': boolean(first('should_clarify', 'clarification')),
            'ticket_keys': chunks(first('expected_ticket_keys').replace(',', '|||')),
        }
    for field in ['reference_context_ids', 'provided_context_ids']:
        values[field] = chunks(
            first(field, 'retrieved_context_ids' if field == 'provided_context_ids' else field)
        )
    return GoldenCase(**values)


def parse_csv(content):
    try:
        rows = list(csv.reader(io.StringIO(content.decode('utf-8-sig')), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError('Use a valid UTF-8 CSV with quoted cells for commas and multiline context.') from exc
    if len(rows) < 2:
        raise ValueError('CSV needs a header and at least one exchange.')
    headers = [re.sub(r'[\s-]+', '_', h.strip().casefold()) for h in rows[0]]
    if len(set(headers)) != len(headers):
        raise ValueError('Evaluation CSV headers must be distinct.')
    if not {'question', 'user_input'} & set(headers) or not {
        'answer',
        'response',
        'reference_answer',
        'reference',
        'ground_truth',
        'expected_answer',
    } & set(headers):
        raise ValueError(
            'Required CSV columns: question and reference_answer (or answer). Optional: reference_contexts, retrieved_contexts, conversation_id.'
        )
    cases = []
    for number, row in enumerate(rows[1:], 2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(headers):
            raise ValueError(
                f'CSV row {number} has {len(row)} cells; expected {len(headers)}. Quote context and answer cells containing commas.'
            )
        try:
            cases.append(convert(dict(zip(headers, row))))
        except Exception as exc:
            raise ValueError(
                f'CSV row {number}: check the question, answer, context arrays and field lengths. {str(exc).splitlines()[0][:120]}'
            ) from exc
    if not 1 <= len(cases) <= 200:
        raise ValueError('Use 1–200 exchanges per dataset.')
    return cases
