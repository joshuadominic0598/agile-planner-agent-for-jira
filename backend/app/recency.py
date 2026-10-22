"""Sort exported snapshots by dates, using issue numbers only as an undated proxy."""

from datetime import datetime, timezone


def timestamp(value):
    if not value or not isinstance(value, str):
        return 0
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        for pattern in (
            '%d/%b/%y %I:%M %p',
            '%d/%b/%y %H:%M',
            '%d/%b/%Y %I:%M %p',
            '%d/%b/%Y %H:%M',
            '%d/%m/%Y %H:%M',
            '%d/%m/%y %H:%M',
        ):
            try:
                parsed = datetime.strptime(value.strip(), pattern)
                break
            except ValueError:
                continue
        else:
            return 0
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()


def rank(row):
    key = row['key'].rsplit('-', 1)
    created = timestamp(row.get('created'))
    return (
        timestamp(row.get('updated')) or created,
        created,
        int(key[-1]) if key[-1].isdigit() else 0,
        key[0],
    )


def latest(rows, limit):
    return sorted(rows, key=rank, reverse=True)[:limit]
