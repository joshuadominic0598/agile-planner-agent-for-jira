"""Evidence checks for specialized acronym definitions; no invented public expansions."""

import re


def evidence_answer(term, sources, question):
    if not re.fullmatch(r'[A-Z][A-Z0-9]{1,12}', term or ''):
        return None
    if not re.search(
        r'\b(?:taxonomy|standard|term|acronym|abbreviation|coding|classification)\b', question, re.I
    ):
        return None

    def safe(value):
        return re.sub(r'[\\`*_{}\[\]<>|#]', '', str(value)).replace('\n', ' ')

    for source in sources:
        match = re.search(
            r'\b' + re.escape(term) + r'\s+(?:stands for|means|is defined as|refers to)\s+([^\n.]{8,220})',
            source.get('source_text', ''),
            re.I,
        )
        if match:
            return f"The exported text describes **{safe(term)}** as “{safe(match[1])}”. ({safe(source['ticket']['key'])})\n\nThis is the export's wording, not independent public verification."
    examples = sources[:2]
    lead = (
        f'**{safe(term)}** appears in these retrieved work items:'
        if examples
        else f'The retrieved CSV text does not define **{safe(term)}**.'
    )
    lines = [lead]
    if examples:
        lines += [''] + [
            f'- **{safe(s["ticket"]["key"])}** — {safe(s["ticket"]["summary"])}' for s in examples
        ]
    lines += [
        '',
        "The retrieved text doesn't verify the acronym's expansion or public definition. A public-source lookup is needed to confirm that meaning.",
    ]
    return '\n'.join(lines)
