from __future__ import annotations

import sqlite3
import threading
import time
import pytest

from tests.p6_support import Harness


def waiting_operation(h, *, tool='send_action'):
    counter = h.side_tool(tool)
    plan = h.operations.create_plan('Send safely', [{
        'requested_tool': tool,
        'parameters': {'recipient': 'example.test', 'reference': 'fixture'},
    }])
    result = h.operations.execute(plan['id'], **h.authority())
    operation = result['operation']
    assert operation['status'] == 'waiting_approval'
    assert counter.value == 0
    return plan, operation, counter


def test_consequential_action_uses_existing_approval_and_executes_once_after_grant(tmp_path):
    h = Harness(tmp_path)
    try:
        _, operation, counter = waiting_operation(h)
        approved = h.operations.approve(operation['operation_id'], **h.authority())
        assert approved['status'] == 'verified'
        assert approved['outcome_state'] == 'VERIFIED'
        assert counter.value == 1
        with pytest.raises(PermissionError):
            h.operations.approve(operation['operation_id'], **h.authority())
        assert counter.value == 1
    finally:
        h.close()


def test_approval_denial_causes_no_side_effect(tmp_path):
    h = Harness(tmp_path)
    try:
        _, operation, counter = waiting_operation(h)
        rejected = h.operations.reject(operation['operation_id'], **h.authority())
        assert rejected['status'] == 'cancelled'
        assert rejected['outcome_state'] == 'CANCELLED'
        assert counter.value == 0
    finally:
        h.close()


def test_owner_device_and_session_mismatch_fail_closed(tmp_path):
    h = Harness(tmp_path)
    try:
        _, operation, counter = waiting_operation(h)
        with pytest.raises(PermissionError, match='owner mismatch'):
            h.operations.approve(operation['operation_id'], **h.authority(owner_id='attacker'))
        with pytest.raises(PermissionError, match='device mismatch'):
            h.operations.approve(operation['operation_id'], **h.authority(device_id='device-2'))
        with pytest.raises(PermissionError, match='session mismatch'):
            h.operations.approve(operation['operation_id'], **h.authority(session_id='session-2'))
        assert counter.value == 0
    finally:
        h.close()


def test_security_epoch_change_revokes_pending_approval(tmp_path):
    h = Harness(tmp_path)
    try:
        _, operation, counter = waiting_operation(h)
        h.executor.invalidate_pending_approvals()
        result = h.operations.approve(operation['operation_id'], **h.authority())
        assert result['status'] == 'failed'
        assert result['outcome_state'] == 'FAILED'
        assert counter.value == 0
    finally:
        h.close()


def test_expired_approval_fails_closed_without_side_effect(tmp_path):
    h = Harness(tmp_path)
    try:
        _, operation, counter = waiting_operation(h)
        with sqlite3.connect(h.executor.approvals.path) as con:
            con.execute('UPDATE approval_tickets SET expires_at=0 WHERE id=?', (h.operations._delegation(operation['operation_id'])['approval_id'],))
        result = h.operations.approve(operation['operation_id'], **h.authority())
        assert result['status'] == 'recovery_required'
        assert counter.value == 0
    finally:
        h.close()


def test_reauthentication_required_step_never_dispatches_without_fresh_owner_proof(tmp_path):
    h = Harness(tmp_path)
    try:
        counter = h.side_tool('reauth_send', requires_reauth=True)
        plan = h.operations.create_plan('Reauth send', [{
            'requested_tool': 'reauth_send',
            'parameters': {'recipient': 'example.test', 'reference': 'fixture'},
        }])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        assert waiting['status'] == 'waiting_reauth'
        assert counter.value == 0
        stale = time.time() - 3600
        still_waiting = h.operations.execute(plan['id'], **h.authority(reauthenticated_at=stale))['operation']
        assert still_waiting['status'] == 'waiting_reauth'
        fresh = h.operations.execute(plan['id'], **h.authority(reauthenticated_at=time.time()))['operation']
        assert fresh['status'] == 'waiting_approval'
        assert counter.value == 0
    finally:
        h.close()


def test_concurrent_approval_race_consumes_existing_ticket_at_most_once(tmp_path):
    h = Harness(tmp_path)
    try:
        _, operation, counter = waiting_operation(h)
        results = []
        errors = []

        def approve():
            try:
                results.append(h.operations.approve(operation['operation_id'], **h.authority()))
            except Exception as exc:
                errors.append(type(exc).__name__)

        threads = [threading.Thread(target=approve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        assert counter.value == 1
        assert h.operations.operation(operation['operation_id'])['status'] == 'verified'
        assert len(results) == 1
        assert errors == ['PermissionError']
    finally:
        h.close()


def test_changed_parameters_cannot_reuse_existing_approval(tmp_path):
    h = Harness(tmp_path)
    try:
        _, operation, counter = waiting_operation(h)
        internal = h.operations._delegation(operation['operation_id'])
        approval_id = internal['approval_id']
        paused = h.executor._load_paused(approval_id)
        paused['plan']['steps'][paused['index']]['parameters']['recipient'] = 'tampered.example'
        h.executor.approvals.save_context(approval_id, {k: v for k, v in paused.items() if k != 'cancel_event'})
        result = h.operations.approve(operation['operation_id'], **h.authority())
        assert result['status'] == 'recovery_required'
        assert result['outcome_state'] == 'UNCERTAIN'
        assert counter.value == 0
    finally:
        h.close()


def test_consumed_approval_cannot_be_replayed(tmp_path):
    h = Harness(tmp_path)
    try:
        _, operation, counter = waiting_operation(h)
        approved = h.operations.approve(operation['operation_id'], **h.authority())
        assert approved['status'] == 'verified'
        assert counter.value == 1
        try:
            h.operations.approve(operation['operation_id'], **h.authority())
            replay_blocked = False
        except PermissionError:
            replay_blocked = True
        assert replay_blocked is True
        assert counter.value == 1
    finally:
        h.close()

def test_model_plan_memory_or_reminder_cannot_self_authorize(tmp_path):
    h = Harness(tmp_path)
    try:
        _, operation, counter = waiting_operation(h)
        assert operation['status'] == 'waiting_approval'
        assert counter.value == 0
        with pytest.raises(ValueError):
            h.gate.record_external_proof('p3.automation', True, source='llm')
        with pytest.raises(PermissionError):
            h.operations.approve(operation['operation_id'], **h.authority(owner_id='model'))
        assert counter.value == 0
    finally:
        h.close()
