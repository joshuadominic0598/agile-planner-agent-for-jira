"""Load packaged prompts explicitly during application composition."""

from pathlib import Path


def load_skill_documents():
    folder = Path(__file__).with_name('skills')
    return {
        name: (folder / (name + '.md')).read_text(encoding='utf-8')
        for name in ('sprint', 'project', 'backlog', 'employee', 'management', 'capacity')
    }
