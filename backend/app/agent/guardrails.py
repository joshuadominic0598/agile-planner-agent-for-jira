"""Pre-workflow input screening; semantic relevance is resolved by the selected model."""

import re
import unicodedata

from better_profanity import profanity
from fastapi import HTTPException

from .. import store
from ..observability.telemetry import clean, now


def validate(message, dataset_id='', session_id=''):
    text = unicodedata.normalize('NFKC', message).strip()
    reason = ''
    if not text or len(text) > 20000 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text):
        reason = 'Use a readable message without control characters.'
    elif profanity.contains_profanity(
        re.sub(
            r'\bkill\b(?=.{0,40}\b(?:process|worker|task|thread|job|container|server)\b)',
            'stop',
            text,
            flags=re.I,
        )
    ):
        reason = 'Please rephrase without abusive or inappropriate language.'
    elif re.search(
        r'\b(?:reveal|print|show|steal|exfiltrate)\b.{0,60}\b(?:api keys?|secret keys?|credentials|system prompt)\b',
        text,
        re.I,
    ):
        reason = 'I can help with project tickets, but cannot disclose credentials or internal instructions.'
    elif re.search(r'\b(?:sk-[\w-]{20,}|AIza[\w-]{25,})\b', text):
        reason = 'Keep API keys out of chat. Add them through Configure instead.'
    if reason:
        store.mongo().agent_guardrails.insert_one(
            {
                'dataset_id': dataset_id,
                'session_id': session_id,
                'created_at': now(),
                'decision': 'blocked',
                'reason': reason,
                'input': clean(text, 1000),
            }
        )
        raise HTTPException(422, reason)
    return text
