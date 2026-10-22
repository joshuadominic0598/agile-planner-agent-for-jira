"""Free, on-device embedding choices and bounded character-based chunking."""

import os
from pathlib import Path
from urllib.parse import urlsplit

PROFILES = {
    'small': {
        'model': 'embeddinggemma',
        'label': 'Smaller · EmbeddingGemma',
        'chunk_characters': 1000,
        'chunk_overlap': 200,
        'download': '622 MB',
    },
    'large': {
        'model': 'qwen3-embedding:4b',
        'label': 'Larger · Qwen3 Embedding 4B',
        'chunk_characters': 3000,
        'chunk_overlap': 500,
        'download': '2.5 GB',
    },
}


def local_base():
    default = (
        'http://host.docker.internal:11434/v1'
        if Path('/.dockerenv').exists()
        else 'http://127.0.0.1:11434/v1'
    )
    base = os.getenv('JIRA_LOCAL_EMBEDDING_BASE_URL', default).rstrip('/')
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {'http', 'https'}
        or parsed.hostname not in {'localhost', '127.0.0.1', '::1', 'host.docker.internal'}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {'', '/v1'}
    ):
        raise ValueError('Private embeddings require a local Ollama URL (localhost or host.docker.internal).')
    return base.removesuffix('/v1')


def apply_profile(config, preset):
    if preset == 'lexical':
        config = {
            **config,
            'provider': 'local',
            'model': '',
            'base': '',
            'key': '',
            'signature': 'local:tfidf-v1',
        }
    elif preset in PROFILES:
        profile = PROFILES[preset]
        base = local_base()
        config = {
            'provider': 'compatible',
            'model': profile['model'],
            'base': base,
            'key': '',
            'signature': f'ollama:{profile["model"]}:{base}',
            'ollama': True,
        }
    profile = PROFILES.get(preset, PROFILES['small'])
    return {
        **config,
        'preset': preset,
        'chunk_characters': profile['chunk_characters'],
        'chunk_overlap': profile['chunk_overlap'],
        'batch_size': 8 if preset == 'large' else 32,
        'signature': f'{config["signature"]}:chunks-{profile["chunk_characters"]}-{profile["chunk_overlap"]}',
    }


def ticket_chunks(sections, title, maximum, overlap):
    """Pack one ticket's fields; repeat labels without losing or mixing field text."""
    prefix = 'Title: ' + title.replace('\n', ' ')[:160] + '\n'
    sections = dict(sections)
    if len(title) > 160 or '\n' in title:
        sections = {'Full summary': title, **sections}
    empty = '[no excerpt in this chunk]'

    def render(parts):
        return prefix + '\n'.join(f'{name}: {parts.get(name) or empty}' for name in sections)

    capacity = maximum - len(render({}))
    if not 0 <= overlap < capacity:
        raise ValueError('Chunk overlap must be smaller than the narrative capacity.')
    complete = render(sections)
    if len(complete) <= maximum:
        yield complete
        return

    # A single narrative stream gives adjacent chunks exact overlap even when a
    # window crosses from description to criteria or comments. Restore field
    # labels when rendering; ticket identity never enters another ticket's stream.
    spans, offset = [], 0
    for name, value in sections.items():
        spans.append((name, offset, offset + len(value), value))
        offset += len(value)
    narrative = ''.join(sections.values())

    def parts_between(start, end):
        return {
            name: value[max(start - left, 0) : min(end, right) - left]
            for name, left, right, value in spans
            if left < end and right > start and value
        }

    start = 0
    while start < len(narrative):
        end = min(start + capacity, len(narrative))
        # Each populated field replaces its empty marker, freeing that space.
        # Extending can encounter another field, so settle the small fixed point.
        while True:
            present = len(parts_between(start, end))
            extended = min(start + capacity + len(empty) * present, len(narrative))
            if extended == end:
                break
            end = extended
        if end < len(narrative):
            lower = start + max(overlap + 1, (end - start) * 3 // 4)
            for separator in ('\n\n', '\n', '. ', ' '):
                boundary = narrative.rfind(separator, lower, end)
                if boundary >= lower:
                    candidate = boundary + len(separator)
                    # Dropping a populated field restores its placeholder.
                    if len(render(parts_between(start, candidate))) <= maximum:
                        end = candidate
                        break
        yield render(parts_between(start, end))
        if end == len(narrative):
            break
        start = end - overlap
