"""Explicit fresh-workspace reset with a recoverable local archive. Never runs at startup."""

import argparse
import os
import shutil
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile

from bson import json_util

from . import store
from .paths import data_dir


def reset(confirm):
    if confirm != 'RESET':
        raise ValueError('Pass --confirm RESET to clear the workspace.')
    root = data_dir()
    backups = root / 'backups'
    backups.mkdir(exist_ok=True)
    path = backups / ('workspace-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.zip')
    db = store.mongo()
    files = [
        p
        for p in root.rglob('*')
        if p.is_file()
        and backups not in p.parents
        and (
            p.name.startswith(('retrieval.sqlite3', 'legacy.sqlite3'))
            or 'uploads' in p.relative_to(root).parts
            or p.name == '.agent-secret-key'
        )
    ]
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for name in db.list_collection_names():
            archive.writestr('mongodb/' + name + '.json', json_util.dumps(list(db[name].find())))
        for file in files:
            archive.write(file, 'files/' + str(file.relative_to(root)))
    os.chmod(path, 0o600)
    db.client.drop_database(db.name)
    for file in files:
        file.unlink()
    uploads = root / 'uploads'
    if uploads.exists():
        shutil.rmtree(uploads)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm', required=True)
    print('Previous workspace archived at', reset(parser.parse_args().confirm))
