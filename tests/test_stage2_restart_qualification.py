from __future__ import annotations

import pytest

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_autonomy_runtime
from security.approvals import ApprovalManager


install_autonomy_runtime(AdvancedAutonomy)


class _Decision:
    allowed = True
    reason = 'ok'


class _Gate:
    def decision(self, _action):
        return _Decision()


class _Operations:
    def __init__(self):
        self.approved = []
        self.rejected = []

    def approve(self, operation_id, **_kwargs):
        self.approved.append(operation_id)
        return {
            'operation_id': operation_id,
            'status': 'completed',
            'outcome_state': 'VERIFIED',
        }

    def reject(self, operation_id, **_kwargs):
        self.rejected.append(operation_id)
        return {
            'operation_id': operation_id,
            'status': 'cancelled',
            'outcome_state': 'CANCELLED',
        }


def _ticket(manager: ApprovalManager, execution='e1'):
    params = {'recipient': 'owner@example.com', 'body': 'hello'}
    ticket = manager.create(
        execution,
        'send_message',
        params,
        owner_id='owner',
        device_id='d1',
        session_id='s1',
        destination=params['recipient'],
        data_classification='internal',
    )
    manager.save_context(ticket.id, {
        'execution_id': execution,
        'plan': {'steps': [{'tool': 'send_message', 'parameters': params}]},
        'index': 0,
        'results': {},
        'history': [],
        'device_id': 'd1',
        'session_id': 's1',
        'owner_id': 'owner',
        'conversation_id': 'c1',
        'sensitivity': 'internal',
    })
    return ticket, params


def _approve(manager: ApprovalManager, ticket, params, *, now=None):
    return manager.approve(
        ticket.id,
        ticket.execution_id,
        ticket.tool_name,
        params,
        now=now,
        owner_id='owner',
        device_id='d1',
        session_id='s1',
        destination=params['recipient'],
        data_classification='internal',
    )


def test_approved_before_execution_survives_runtime_reconstruction(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    runtime_a = ApprovalManager(path=path)
    ticket, params = _ticket(runtime_a)
    _approve(runtime_a, ticket, params)
    assert runtime_a.record(ticket.id)['status'] == 'approved'

    runtime_b = ApprovalManager(path=path)
    record = runtime_b.record(ticket.id)
    assert record['status'] == 'approved'
    assert runtime_b.context(ticket.id)['execution_id'] == ticket.execution_id
    claim = runtime_b.begin_dispatch(ticket.id, worker_id='runtime-b')
    assert claim['dispatch'] is True
    assert claim['ticket'].id == ticket.id


def test_restart_during_dispatch_never_blindly_redispatches(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    runtime_a = ApprovalManager(path=path)
    ticket, params = _ticket(runtime_a)
    _approve(runtime_a, ticket, params)
    claim = runtime_a.begin_dispatch(ticket.id, worker_id='runtime-a', now=10, lease_seconds=5)
    assert claim['dispatch'] is True

    runtime_b = ApprovalManager(path=path)
    still_owned = runtime_b.begin_dispatch(ticket.id, worker_id='runtime-b', now=11, lease_seconds=5)
    assert still_owned['dispatch'] is False
    assert still_owned['status'] == 'dispatching'

    after_lease = ApprovalManager(path=path).begin_dispatch(
        ticket.id, worker_id='runtime-c', now=16, lease_seconds=5
    )
    assert after_lease['dispatch'] is False
    assert after_lease['status'] == 'recovery_required'
    assert ApprovalManager(path=path).record(ticket.id)['failure_code'] == 'dispatch_lease_expired'


def test_approval_expiry_boundary_is_fail_closed_across_reconstruction(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    runtime_a = ApprovalManager(ttl_seconds=5, path=path)
    ticket, params = _ticket(runtime_a)

    before = ticket.expires_at - 0.0001
    _approve(runtime_a, ticket, params, now=before)
    assert runtime_a.record(ticket.id)['status'] == 'approved'

    other, other_params = _ticket(runtime_a, execution='e2')
    runtime_b = ApprovalManager(ttl_seconds=5, path=path)
    with pytest.raises(PermissionError, match='expired'):
        _approve(runtime_b, other, other_params, now=other.expires_at)
    assert runtime_b.record(other.id)['status'] == 'expired'

    late, late_params = _ticket(runtime_b, execution='e3')
    runtime_c = ApprovalManager(ttl_seconds=5, path=path)
    with pytest.raises(PermissionError, match='expired'):
        _approve(runtime_c, late, late_params, now=late.expires_at + 1)
    assert runtime_c.record(late.id)['status'] == 'expired'


def _persist_waiting_p10(path):
    autonomy = AdvancedAutonomy(gate=_Gate(), path=path)
    goal = autonomy.create_goal('Send governed report', owner_id='owner', session_id='s1')
    plan = autonomy.create_plan(
        goal['id'],
        [{
            'id': 'k1',
            'objective': 'send report',
            'requested_tool': 'send_message',
            'parameters': {'recipient': 'owner@example.com'},
            'consequential': True,
            'approval_required': True,
        }],
        owner_id='owner',
    )
    plan['state'] = 'WAITING_APPROVAL'
    plan['device_id'] = 'd1'
    plan['session_id'] = 's1'
    plan['tasks'][0]['status'] = 'WAITING_APPROVAL'
    plan['tasks'][0]['operation_id'] = 'o1'
    plan['tasks'][0]['approval_ref'] = 'a1'
    autonomy._save_plan(plan)
    autonomy._db.close()
    return goal['id'], plan['id']


def test_p10_waiting_approval_restart_preserves_identity_and_continues_same_operation(tmp_path):
    path = tmp_path / 'autonomy.sqlite3'
    goal_id, plan_id = _persist_waiting_p10(path)
    operations = _Operations()
    runtime_b = AdvancedAutonomy(gate=_Gate(), operations=operations, path=path)

    restored = runtime_b.plan(plan_id, owner_id='owner')
    task = restored['tasks'][0]
    assert restored['goal_id'] == goal_id
    assert restored['state'] == 'WAITING_APPROVAL'
    assert task['id'] == 'k1'
    assert task['approval_ref'] == 'a1'
    assert task['operation_id'] == 'o1'

    completed = runtime_b.approve_task(
        plan_id,
        'k1',
        owner_id='owner',
        device_id='d1',
        session_id='s1',
    )
    assert operations.approved == ['o1']
    assert completed['id'] == plan_id
    assert completed['tasks'][0]['id'] == 'k1'
    assert completed['tasks'][0]['result_ref'] == 'o1'
    assert completed['state'] == 'COMPLETED'


def test_p10_denial_after_restart_cancels_same_operation_and_cannot_repeat(tmp_path):
    path = tmp_path / 'autonomy.sqlite3'
    _goal_id, plan_id = _persist_waiting_p10(path)
    operations = _Operations()
    runtime_b = AdvancedAutonomy(gate=_Gate(), operations=operations, path=path)

    cancelled = runtime_b.deny_task(
        plan_id,
        'k1',
        owner_id='owner',
        device_id='d1',
        session_id='s1',
    )
    assert operations.rejected == ['o1']
    assert cancelled['id'] == plan_id
    assert cancelled['state'] == 'CANCELLED'
    assert cancelled['tasks'][0]['status'] == 'CANCELLED'

    with pytest.raises(PermissionError):
        runtime_b.deny_task(
            plan_id,
            'k1',
            owner_id='owner',
            device_id='d1',
            session_id='s1',
        )
    assert operations.rejected == ['o1']
