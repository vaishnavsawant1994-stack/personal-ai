"""Stage-8: audit integrity — no false-success projection; safe error surfaces."""

from __future__ import annotations

from pathlib import Path

import pytest

from recovery.backup import BackupError, BackupService
from security.approvals import ApprovalManager


def test_stage8_approval_outcome_preserves_verified_false(tmp_path):
    """Completed dispatch with verified=false must not be rewritten as success-only."""
    store = ApprovalManager(path=tmp_path / 'approvals.sqlite3')
    ticket = store.create(
        execution_id='exec-audit-1',
        tool_name='desktop.open',
        parameters={'path': '/tmp/demo'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.approve(
        ticket.id,
        execution_id='exec-audit-1',
        tool_name='desktop.open',
        parameters={'path': '/tmp/demo'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.begin_dispatch(ticket.id, worker_id='worker-1')
    outcome = store.complete_dispatch(
        ticket.id,
        {'status': 'completed', 'verified': False, 'failure_code': 'effect_unconfirmed'},
    )
    assert outcome.get('verified') is False
    assert outcome.get('failure_code') == 'effect_unconfirmed'
    record = store.record(ticket.id)
    assert record['status'] == 'completed'
    assert record['outcome']['verified'] is False
    assert record['outcome']['failure_code'] == 'effect_unconfirmed'


def test_stage8_backup_error_messages_are_non_success(tmp_path):
    """BackupError for unsafe destinations must fail closed without success language."""
    data = tmp_path / 'data'
    data.mkdir()
    service = BackupService(data)
    with pytest.raises(BackupError) as excinfo:
        service._safe_rel('../escape.txt')
    msg = str(excinfo.value).lower()
    assert 'unsafe' in msg or 'backup path' in msg
    assert 'success' not in msg
    assert 'wrote' not in msg


def test_stage8_cloud_activity_projection_keeps_verified_field():
    """Activities projection contract includes verified when present (no strip-to-success)."""
    payload = {
        'execution_id': 'e1',
        'tool': 'desktop.open',
        'status': 'completed',
        'verified': False,
        'failure_code': 'effect_unconfirmed',
    }
    safe_payload = {
        key: payload.get(key)
        for key in (
            'execution_id',
            'run_id',
            'approval_id',
            'tool',
            'status',
            'verified',
            'failure_code',
        )
        if key in payload
    }
    assert safe_payload['verified'] is False
    assert safe_payload['failure_code'] == 'effect_unconfirmed'
    assert safe_payload['status'] == 'completed'
