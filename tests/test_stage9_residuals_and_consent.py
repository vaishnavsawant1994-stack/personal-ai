"""Stage 9: residual findings and the partial consent matrix stay tied to code."""

from __future__ import annotations

import json
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


def test_stage9_legacy_pwa_routes_are_off_unless_opted_in():
    source = (ROOT / 'server' / 'iphone_pwa.py').read_text(encoding='utf-8')
    assert 'include_legacy_runtime_routes: bool = False' in source
    cloud = (ROOT / 'server' / 'cloud_app.py').read_text(encoding='utf-8')
    assert 'include_legacy_runtime_routes=False' in cloud


def test_stage9_emergency_stop_writers_converge():
    """Official writers set both stores. A mismatch is not reported as success."""
    relay = (ROOT / 'cloud_runtime' / 'relay.py').read_text(encoding='utf-8')
    owner = (ROOT / 'server' / 'owner_product.py').read_text(encoding='utf-8')
    assert 'self.sessions.set_emergency_stop(enabled)' in relay
    assert 'tools.set_emergency_stop(enabled)' in relay
    assert "emergency_stop_diverged" in relay
    assert "runtime.get('cloud_sessions')" in owner
    assert 'sessions.set_emergency_stop(body.enabled)' in owner
    note = (ROOT / 'docs' / 'STAGE9_RESIDUALS.md').read_text(encoding='utf-8')
    assert 'R2' in note
    assert 'One sqlite table was not deleted' in note


def test_stage9_consent_matrix_matches_classification():
    matrix = (ROOT / 'docs' / 'STAGE9_CONSENT_MATRIX.md').read_text(encoding='utf-8')
    facts = json.loads((ROOT / 'docs' / 'stage9_route_classification.json').read_text(encoding='utf-8'))
    assert 'not a Stage 9 freeze' in matrix
    assert 'GET /capabilities/api/status' in matrix
    assert 'POST /iphone/api/logout' in matrix
    assert 'closed after the Stage 9 freeze' in matrix
    for row in facts:
        if row['method'] == 'GET' and row['status'] == 'surface-specific-ok':
            continue
        assert f"| {row['method']} | {row['path']} |" in matrix
        if row['evidence']:
            source = (ROOT / row['file']).read_text(encoding='utf-8')
            assert row['evidence'] in source
    assert sum(1 for row in facts if row['status'] == 'gap') == 0
    assert sum(1 for row in facts if row['status'] == 'legacy-opt-in') == 7
