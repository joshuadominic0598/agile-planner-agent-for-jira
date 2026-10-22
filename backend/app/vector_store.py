"""SQLite holds only the rebuildable narrative retrieval and graph index."""

import sqlite3
from contextlib import contextmanager

from .paths import data_dir


@contextmanager
def connect():
    conn = sqlite3.connect(data_dir() / 'retrieval.sqlite3', timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
