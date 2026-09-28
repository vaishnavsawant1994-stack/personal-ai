"""Stage 9 WP2: the census must list every production route decorator."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / 'docs' / 'stage9_entrypoint_census.json'


def _decorators():
    found = []
    for path in sorted(ROOT.rglob('*.py')):
        if any(part in path.parts for part in ('.git', 'tests', '__pycache__', '.venv')):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        prefix = ''
        match = re.search(r"APIRouter\(\s*prefix\s*=\s*['\"]([^'\"]+)['\"]", text)
        if match:
            prefix = match.group(1)
        for line_no, line in enumerate(text.splitlines(), 1):
            deco = re.search(
                r"@(?:app|r|router)\.(get|post|put|patch|delete|websocket)\(\s*['\"]([^'\"]+)",
                line,
            )
            if not deco:
                continue
            rel = path.relative_to(ROOT).as_posix()
            raw = deco.group(2)
            full = prefix + raw if raw.startswith('/') else prefix + '/' + raw
            if rel == 'server/connector_knowledge_api.py':
                full = '/iphone/api/connectors' + raw
            found.append((rel, line_no, deco.group(1).upper(), full))
    return found


def test_stage9_census_covers_every_route_decorator():
    census = json.loads(CENSUS.read_text(encoding='utf-8'))
    listed = {(row['file'], row['line'], row['method'], row['path']) for row in census}
    live = set(_decorators())
    assert live == listed
    assert any(row['path'] == '/workflows' and row['status'] == 'gap' for row in census)
    assert any(row['status'] == 'inventoried' for row in census)
