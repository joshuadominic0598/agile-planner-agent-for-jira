"""Resolve application files from the project, independent of the shell directory."""

import os
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[2]
    if Path(__file__).resolve().parent.parent.name == 'backend'
    else Path(__file__).resolve().parents[1]
)


def data_dir():
    configured = Path(os.environ.get('JIRA_DATA_DIR', 'resources/app')).expanduser()
    path = configured if configured.is_absolute() else ROOT / configured
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
