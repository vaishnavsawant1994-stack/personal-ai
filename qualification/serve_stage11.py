"""Start the Stage 11 qualification process for this checkout.

The process is not production and not the public p2 site. It does not mark any
Stage 11 row passed. Run it only after the tree matches the commit you intend
to name.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qualification.stage11_environment import DEFAULT_DATA_NAME, qualification_process


def _git(args: list[str]) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def main() -> int:
    sha = _git(['rev-parse', 'HEAD'])
    dirty = [
        line for line in _git(['status', '--porcelain']).splitlines()
        if line and DEFAULT_DATA_NAME not in line and '.pytest_cache' not in line
    ]
    if dirty:
        print('refusing_dirty_tree', file=sys.stderr)
        return 2
    data_dir = Path(os.environ.get('STAGE11_DATA_DIR', ROOT / DEFAULT_DATA_NAME))
    host = os.environ.get('STAGE11_BIND_HOST', '127.0.0.1')
    port = int(os.environ.get('STAGE11_PORT', '8766'))
    os.environ.update(qualification_process(source_sha=sha, data_dir=data_dir, host=host))
    import uvicorn
    print(f'stage11-qualification source_sha={sha} pwa=http://{host}:{port}/iphone/', flush=True)
    uvicorn.run('server.cloud_app:app', host=host, port=port, log_level='info')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
