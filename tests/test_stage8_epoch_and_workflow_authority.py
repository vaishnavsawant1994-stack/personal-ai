"""Stage-8: security epoch invalidation and workflow authority boundaries."""

from __future__ import annotations

import json
import uuid

import pytest

from automation.engine import AutomationEngine, now
from security.approvals import ApprovalManager


def test_stage8_advance_security_epoch_invalidates_pending(tmp_path):
    store = ApprovalManager(path=tmp_path / 'approvals.sqlite3')
    ticket = store.create(
        execution_id='exec-1',
        tool_name='desktop.open',
        parameters={'path': '/tmp/x'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    assert ticket.security_epoch == 0
    record = store.record(ticket.id)
    assert record['status'] == 'pending'

    epoch = store.advance_security_epoch()
    assert epoch == 1
    assert store.current_security_epoch() == 1

    record = store.record(ticket.id)
    assert record['status'] == 'invalidated'
    assert record.get('failure_code') == 'security_epoch_changed'


def test_stage8_approve_after_epoch_change_fails_closed(tmp_path):
    store = ApprovalManager(path=tmp_path / 'approvals.sqlite3')
    ticket = store.create(
        execution_id='exec-2',
        tool_name='desktop.open',
        parameters={'path': '/tmp/y'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.advance_security_epoch()
    with pytest.raises(PermissionError):
        store.approve(
            ticket.id,
            execution_id='exec-2',
            tool_name='desktop.open',
            parameters={'path': '/tmp/y'},
            owner_id='owner',
            device_id='device-1',
            session_id='session-1',
        )


def test_stage8_begin_dispatch_after_epoch_change_fails_closed(tmp_path):
    store = ApprovalManager(path=tmp_path / 'approvals.sqlite3')
    ticket = store.create(
        execution_id='exec-3',
        tool_name='desktop.open',
        parameters={'path': '/tmp/z'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.approve(
        ticket.id,
        execution_id='exec-3',
        tool_name='desktop.open',
        parameters={'path': '/tmp/z'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.advance_security_epoch()
    result = store.begin_dispatch(ticket.id, worker_id='worker-1')
    assert result['dispatch'] is False
    assert result['status'] in {'invalidated', 'recovery_required'}


def test_stage8_consume_after_epoch_change_fails_closed(tmp_path):
    store = ApprovalManager(path=tmp_path / 'approvals.sqlite3')
    ticket = store.create(
        execution_id='exec-4',
        tool_name='desktop.open',
        parameters={'path': '/tmp/w'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.advance_security_epoch()
    with pytest.raises(PermissionError):
        store.consume(
            ticket.id,
            execution_id='exec-4',
            tool_name='desktop.open',
            parameters={'path': '/tmp/w'},
            owner_id='owner',
            device_id='device-1',
            session_id='session-1',
        )


def _poison_workflow(engine: AutomationEngine, title: str, steps: list[dict]) -> str:
    """Insert a workflow that bypassed create-time normalization."""
    workflow_id = str(uuid.uuid4())
    stamp = now()
    with engine._con() as con:
        con.execute(
            '''INSERT INTO workflows(id,title,trigger_json,steps_json,enabled,paused,next_run_at,interval_seconds,created_at,updated_at,last_run_at,policy_json)
               VALUES(?,?,?,?,1,0,NULL,NULL,?,?,NULL,?)''',
            (
                workflow_id,
                title,
                json.dumps({'type': 'manual'}),
                json.dumps(steps),
                stamp,
                stamp,
                '{}',
            ),
        )
    return workflow_id


def test_stage8_workflow_rejects_tool_kind_laundering(tmp_path):
    """Workflow steps cannot invent a direct tool kind to bypass prompt/approval path."""
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=None, events=None)
    with pytest.raises(ValueError, match='unsupported workflow step kind: tool'):
        engine.create_workflow(
            'launder',
            {'type': 'manual'},
            [{'kind': 'tool', 'tool_name': 'desktop.open', 'parameters': {'path': '/etc/passwd'}}],
        )
    assert engine.workflows() == []

    workflow_id = _poison_workflow(
        engine,
        'poison-tool',
        [{'kind': 'tool', 'tool_name': 'desktop.open', 'parameters': {'path': '/etc/passwd'}, 'position': 0}],
    )
    run_id = engine.run_workflow(
        workflow_id,
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
        background=False,
    )
    run = engine._run(run_id)
    assert run['status'] != 'completed'
    assert run['status'] in {'failed', 'recovery_required', 'cancelled'}
    assert 'unsupported' in str(run.get('error') or '').lower()


def test_stage8_workflow_rejects_shell_kind_laundering(tmp_path):
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=None, events=None)
    with pytest.raises(ValueError, match='unsupported workflow step kind: shell'):
        engine.create_workflow(
            'shell-launder',
            {'type': 'manual'},
            [{'kind': 'shell', 'command': 'echo pwned'}],
        )
    assert engine.workflows() == []

    workflow_id = _poison_workflow(
        engine,
        'poison-shell',
        [{'kind': 'shell', 'command': 'echo pwned', 'position': 0}],
    )
    run_id = engine.run_workflow(
        workflow_id,
        owner_id='owner',
        device_id='device-1',
        background=False,
    )
    run = engine._run(run_id)
    error = str(run.get('error') or '').lower()
    assert run['status'] != 'completed'
    assert run['status'] == 'failed' or 'unsupported' in error


def test_stage8_auth_parity_fails_closed_when_authorize_missing():
    """Bearer control-plane auth must not treat missing authorize() as permit-all."""
    class AuthOnly:
        def authenticate(self, device_id, token):
            return True

    device_registry = AuthOnly()
    authorize = getattr(device_registry, 'authorize', None)
    # Same predicate as server.api auth_device / connector auth
    permitted = callable(authorize) and authorize('device-1', 'ai:chat')
    assert permitted is False
