"""Stage 9 WP1: one class owns each security concept. Readers may be many."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNERS = {
    'class ApprovalManager': 'security/approvals.py',
    'class DeviceRegistry': 'devices/registry.py',
    'class ContinuityService': 'devices/continuity.py',
    'class KnowledgeStore': 'knowledge/store.py',
    'class KnowledgeAuthority': 'knowledge/governance.py',
    'class PwaSessionStore': 'security/pwa_sessions.py',
    'class CloudSessionStore': 'cloud_runtime/security.py',
}


def _production_py():
    for path in ROOT.rglob('*.py'):
        if any(part in path.parts for part in ('.git', 'tests', '__pycache__', '.venv')):
            continue
        yield path


def test_stage9_security_concepts_have_one_class_definition():
    found = {needle: [] for needle in OWNERS}
    for path in _production_py():
        text = path.read_text(encoding='utf-8')
        rel = path.relative_to(ROOT).as_posix()
        for needle in OWNERS:
            if needle in text:
                found[needle].append(rel)
    for needle, owner in OWNERS.items():
        assert found[needle] == [owner], (needle, found[needle])


def test_stage9_cloud_app_does_not_mount_legacy_pwa_authorities():
    """Production cloud must not keep a second live voice/approval/conversation route."""
    text = (ROOT / 'server' / 'cloud_app.py').read_text(encoding='utf-8')
    assert 'include_legacy_runtime_routes=False' in text
    pwa = (ROOT / 'server' / 'iphone_pwa.py').read_text(encoding='utf-8')
    for route in (
        "('POST', '/iphone/api/voice/turn')",
        "('POST', '/iphone/api/approval/{approval_id}/approve')",
        "('POST', '/iphone/api/approval/{approval_id}/reject')",
        "('GET', '/iphone/api/conversations')",
        "('POST', '/iphone/api/voice/barge')",
    ):
        assert route in pwa
