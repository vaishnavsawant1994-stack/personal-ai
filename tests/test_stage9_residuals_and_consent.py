"""Stage 9: residual findings and the partial consent matrix stay tied to code."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LEGACY_DUPLICATES = {
    ('POST', '/iphone/api/voice/turn'),
    ('POST', '/iphone/api/voice/barge'),
    ('POST', '/iphone/api/voice/client-event'),
    ('POST', '/iphone/api/approval/{approval_id}/approve'),
    ('POST', '/iphone/api/approval/{approval_id}/reject'),
    ('GET', '/iphone/api/conversations'),
    ('GET', '/iphone/api/conversations/{conversation_id}'),
}


def test_stage9_only_legacy_routes_are_duplicated():
    census = json.loads((ROOT / 'docs' / 'stage9_entrypoint_census.json').read_text(encoding='utf-8'))
    groups: dict[tuple[str, str], set[str]] = {}
    for row in census:
        groups.setdefault((row['method'], row['path']), set()).add(row['file'])
    duplicates = {key for key, files in groups.items() if len(files) > 1}
    assert duplicates == LEGACY_DUPLICATES
    cloud = (ROOT / 'server' / 'cloud_app.py').read_text(encoding='utf-8')
    assert 'include_legacy_runtime_routes=False' in cloud


def test_stage9_emergency_stop_dual_store_is_still_open():
    """T1.1 stays open until one store is the only writer. Do not delete this assertion to look closed."""
    relay = (ROOT / 'cloud_runtime' / 'relay.py').read_text(encoding='utf-8')
    registry = (ROOT / 'tools' / 'registry.py').read_text(encoding='utf-8')
    owner = (ROOT / 'server' / 'owner_product.py').read_text(encoding='utf-8')
    assert 'self.sessions.set_emergency_stop(enabled)' in relay
    assert 'tools.set_emergency_stop(enabled)' in relay
    assert "VALUES('emergency_stop'" in registry
    assert "runtime['tools'].set_emergency_stop(body.enabled)" in owner
    note = (ROOT / 'docs' / 'STAGE9_RESIDUALS.md').read_text(encoding='utf-8')
    assert 'blocks Stage 9 exit' in note
    assert 'Not closed' in note or 'not closed' in note.lower()


def test_stage9_consent_matrix_rows_match_owner_product_source():
    matrix = (ROOT / 'docs' / 'STAGE9_CONSENT_MATRIX.md').read_text(encoding='utf-8')
    source = (ROOT / 'server' / 'owner_product.py').read_text(encoding='utf-8')
    rows = []
    for line in matrix.splitlines():
        if not line.startswith('| ') or '---' in line or 'Scope' in line:
            continue
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if len(cells) != 4:
            continue
        rows.append(cells)
    assert len(rows) >= 15
    for route, scope, _authority, filename in rows:
        assert filename == 'server/owner_product.py'
        assert re.search(r"authenticate\([^)]*" + re.escape(scope), source)
        assert scope in source
        assert 'not done' in matrix.lower() or 'not done' in matrix
    assert 'knowledge:private' not in {row[1] for row in rows}
