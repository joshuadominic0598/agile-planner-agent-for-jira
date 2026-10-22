"""Add one marked synthetic duplicate while preserving Jira's repeated CSV columns."""

import argparse
import csv
import io
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app import importer, store
from app.duplicates import eligible
from app.paths import data_dir


def add(path, dataset=''):
    path = Path(path).resolve()
    with path.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.reader(handle))
    headers = rows[0]
    records = rows[1:]
    if any(len(row) != len(headers) for row in records):
        raise ValueError('CSV has inconsistent row widths; no changes made.')
    positions = {h: [i for i, n in enumerate(headers) if n == h] for h in headers}

    def get(row, name):
        return row[positions[name][0]] if name in positions else ''

    if any('agileplanner-duplicate-test' in ' '.join(row) for row in records):
        print('Duplicate fixture already present.')
        return
    candidates = [
        row
        for row in records
        if eligible({'category': get(row, 'Status Category'), 'status': get(row, 'Status')})
        and 'joshua' not in get(row, 'Assignee').casefold()
        and 'ashwini' not in get(row, 'Assignee').casefold()
        and len(get(row, 'Description')) > 80
    ]
    if not candidates:
        raise ValueError('No suitable To Do ticket with narrative content was found.')
    source = next(
        (r for r in candidates if any('46' in r[i] for i in positions.get('Sprint', []))), candidates[0]
    )
    clone = list(source)
    key = get(source, 'Issue key')
    prefix = key.rsplit('-', 1)[0]
    number = (
        max(
            int(get(r, 'Issue key').rsplit('-', 1)[1])
            for r in records
            if get(r, 'Issue key').startswith(prefix + '-')
            and get(r, 'Issue key').rsplit('-', 1)[1].isdigit()
        )
        + 1
    )
    clone[positions['Issue key'][0]] = f'{prefix}-{number}'
    for field in ('Reporter', 'Creator'):
        if field in positions:
            previous = get(source, field)
            replacement = next(
                (get(r, field) for r in records if get(r, field) and get(r, field) != previous),
                'Synthetic test reporter',
            )
            clone[positions[field][0]] = replacement
    if 'Issue id' in positions:
        clone[positions['Issue id'][0]] = str(
            max(int(get(r, 'Issue id')) for r in records if get(r, 'Issue id').isdigit()) + 1
        )
    if 'Labels' in positions:
        free = next((i for i in positions['Labels'] if not clone[i]), positions['Labels'][-1])
        clone[free] = (clone[free] + ' ' if clone[free] else '') + 'agileplanner-duplicate-test'
    else:
        clone[positions['Description'][0]] += '\nSynthetic duplicate test fixture.'
    # A punctuation-only title change keeps the requirement content almost identical.
    clone[positions['Summary'][0]] = get(source, 'Summary').rstrip('.') + '.'
    backup = Path('resources/backups') / (
        'before-duplicate-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '.csv'
    )
    backup.parent.mkdir(exist_ok=True)
    shutil.copy2(path, backup)
    backup.chmod(0o600)
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerows([headers, *records, clone])
    content = buffer.getvalue().encode('utf-8-sig')
    parsed, metadata = importer.parse_csv(content)
    path.write_bytes(content)
    if dataset:
        created = [pair for pair in parsed if pair[0]['key'] == clone[positions['Issue key'][0]]]
        store.save_issues(dataset, created)
        folder = data_dir() / 'uploads'
        folder.mkdir(exist_ok=True)
        archived = folder / (dataset + '.csv')
        archived.write_bytes(content)
        archived.chmod(0o600)
        metadata['source_file'] = 'uploads/' + dataset + '.csv'
        store.update(dataset, 'ready', 100, 'Analytics ready', metadata)
        store.mongo().duplicate_reviews.delete_many({'dataset_id': dataset})
    print(
        f'Added marked synthetic duplicate {clone[positions["Issue key"][0]]} of {key}; {len(headers)} positional columns preserved. Backup: {backup}'
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('csv')
    parser.add_argument('--dataset', default='')
    args = parser.parse_args()
    add(args.csv, args.dataset)
