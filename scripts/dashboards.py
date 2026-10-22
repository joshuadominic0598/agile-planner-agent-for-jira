"""Launch each operations dashboard independently from the product UI."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def start(kind, port):
    folder = ROOT / 'resources/app'
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            if response.status == 200:
                print(f'{kind.title()} dashboard: http://localhost:{port}/{kind}')
                return
    except Exception:
        pass
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'backend')}
    settings = ROOT / '.env'
    if settings.exists():
        for line in settings.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env.setdefault(key.strip(), value.strip().strip('\'"'))
    log = (folder / (kind + '-dashboard.log')).open('a')
    process = subprocess.Popen(
        [
            sys.executable,
            '-m',
            'uvicorn',
            'app.observability.dashboard:app',
            '--app-dir',
            str(ROOT / 'backend'),
            '--host',
            '127.0.0.1',
            '--port',
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    (folder / (kind + '-dashboard.pid')).write_text(str(process.pid))
    for _ in range(30):
        if process.poll() is not None:
            raise RuntimeError(f'Dashboard failed. Check {kind}-dashboard.log.')
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError('Dashboard startup timed out.')
    print(f'{kind.title()} dashboard: http://localhost:{port}/{kind}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['monitoring', 'evaluation', 'all'])
    args = parser.parse_args()
    if args.kind in {'monitoring', 'all'}:
        start('monitoring', 8012)
    if args.kind in {'evaluation', 'all'}:
        start('evaluation', 8013)
