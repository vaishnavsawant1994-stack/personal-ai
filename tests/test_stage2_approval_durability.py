from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.durable_executor import ApprovalDispatchInProgress, ApprovalRecoveryRequired
from agent.executor import ConfirmationRequired
from cloud_runtime.relay import SecureCloudRelay
from security.approvals import ApprovalManager
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.approval_api import approval_router


def make_ticket(manager: ApprovalManager, *, execution='e1', device='d1', session='s1', params=None):
    params = params or {'recipient': 'owner@example.com', 'body': 'hello'}
    ticket = manager.create(
        execution,
        'send_message',
        params,
        owner_id='owner',
        device_id=device,
        session_id=session,
        destination=params['recipient'],
        data_classification='internal',
    )
    manager.save_context(ticket.id, {
        'execution_id': execution,
        'plan': {'steps': [{'tool': 'send_message', 'parameters': params}]},
        'index': 0,
        'results': {},
        'history': [],
        'device_id': device,
        'session_id': session,
        'owner_id': 'owner',
        'conversation_id': 'c1',
        'sensitivity': 'internal',
    })
    return ticket, params


def approve(manager, ticket, params, *, device='d1', session='s1'):
    return manager.approve(
        ticket.id,
        ticket.execution_id,
        ticket.tool_name,
        params,
        owner_id='owner',
        device_id=device,
        session_id=session,
        destination=params['recipient'],
        data_classification='internal',
    )


def test_pending_approval_survives_real_runtime_reconstruction(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    first = ApprovalManager(path=path)
    ticket, params = make_ticket(first)
    assert first.record(ticket.id)['status'] == 'pending'
    assert first.context(ticket.id)['execution_id'] == 'e1'

    second = ApprovalManager(path=path)
    record = second.record(ticket.id)
    assert record['ticket'].id == ticket.id
    assert record['status'] == 'pending'
    assert second.context(ticket.id)['plan']['steps'][0]['parameters'] == params


def test_approved_before_dispatch_survives_restart_and_dispatches_once(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    first = ApprovalManager(path=path)
    ticket, params = make_ticket(first)
    approve(first, ticket, params)
    assert first.record(ticket.id)['status'] == 'approved'

    restarted = ApprovalManager(path=path)
    assert restarted.record(ticket.id)['status'] == 'approved'
    assert restarted.context(ticket.id)['execution_id'] == 'e1'
    claim = restarted.begin_dispatch(ticket.id, worker_id='worker-after-restart')
    assert claim['dispatch'] is True
    assert ApprovalManager(path=path).begin_dispatch(ticket.id, worker_id='other')['dispatch'] is False


def test_duplicate_and_concurrent_approval_has_one_dispatch_owner(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    seed = ApprovalManager(path=path)
    ticket, params = make_ticket(seed)
    approve(seed, ticket, params)

    winners = []
    statuses = []
    barrier = threading.Barrier(2)

    def contender(worker):
        runtime = ApprovalManager(path=path)
        barrier.wait()
        result = runtime.begin_dispatch(ticket.id, worker_id=worker, lease_seconds=60)
        statuses.append(result['status'])
        if result['dispatch']:
            winners.append(worker)

    a = threading.Thread(target=contender, args=('worker-a',))
    b = threading.Thread(target=contender, args=('worker-b',))
    a.start(); b.start(); a.join(); b.join()
    assert len(winners) == 1
    assert statuses.count('dispatching') == 2


def test_lost_approval_response_replays_completed_result_without_new_dispatch(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    first = ApprovalManager(path=path)
    ticket, params = make_ticket(first)
    approve(first, ticket, params)
    claim = first.begin_dispatch(ticket.id, worker_id='worker-a')
    assert claim['dispatch'] is True
    first.complete_dispatch(ticket.id, {'status': 'completed', 'reply': 'sent', 'verified': True})

    restarted = ApprovalManager(path=path)
    record = restarted.record(ticket.id)
    assert record['status'] == 'completed'
    assert record['outcome']['reply'] == 'sent'
    replay = restarted.begin_dispatch(ticket.id, worker_id='worker-b')
    assert replay['dispatch'] is False
    assert replay['status'] == 'completed'
    assert replay['outcome']['reply'] == 'sent'


def test_expired_dispatch_lease_fails_closed_to_recovery(tmp_path):
    manager = ApprovalManager(path=tmp_path / 'trusted-actions.sqlite3')
    ticket, params = make_ticket(manager)
    approve(manager, ticket, params)
    first = manager.begin_dispatch(ticket.id, worker_id='worker-a', now=10, lease_seconds=5)
    assert first['dispatch'] is True
    second = manager.begin_dispatch(ticket.id, worker_id='worker-b', now=16, lease_seconds=5)
    assert second['dispatch'] is False
    assert second['status'] == 'recovery_required'
    assert manager.record(ticket.id)['failure_code'] == 'dispatch_lease_expired'


def test_mid_dispatch_restart_fences_to_recovery_not_redispatch(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    first = ApprovalManager(path=path)
    ticket, params = make_ticket(first)
    approve(first, ticket, params)
    assert first.begin_dispatch(ticket.id, worker_id='worker-a', now=100, lease_seconds=5)['dispatch'] is True

    restarted = ApprovalManager(path=path)
    probe = restarted.begin_dispatch(ticket.id, worker_id='worker-b', now=106, lease_seconds=5)
    assert probe['dispatch'] is False
    assert probe['status'] == 'recovery_required'
    assert restarted.context(ticket.id)['execution_id'] == 'e1'


def test_security_epoch_invalidates_pending_and_fences_dispatch(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    manager = ApprovalManager(path=path)
    pending, pending_params = make_ticket(manager, execution='pending')
    dispatching, dispatch_params = make_ticket(manager, execution='dispatch')
    approve(manager, dispatching, dispatch_params)
    assert manager.begin_dispatch(dispatching.id, worker_id='w')['dispatch'] is True

    manager.advance_security_epoch()
    assert manager.record(pending.id)['status'] == 'invalidated'
    assert manager.record(dispatching.id)['status'] == 'recovery_required'
    with pytest.raises(PermissionError):
        approve(manager, pending, pending_params)


def test_scope_tampering_device_session_owner_and_payload_fail_closed(tmp_path):
    manager = ApprovalManager(path=tmp_path / 'trusted-actions.sqlite3')
    ticket, params = make_ticket(manager)
    changed = dict(params); changed['recipient'] = 'other@example.com'
    with pytest.raises(PermissionError):
        manager.approve(ticket.id, 'e1', 'send_message', changed, owner_id='owner', device_id='d1', session_id='s1', destination=changed['recipient'], data_classification='internal')
    with pytest.raises(PermissionError):
        manager.approve(ticket.id, 'e1', 'send_message', params, owner_id='owner', device_id='d2', session_id='s1', destination=params['recipient'], data_classification='internal')
    with pytest.raises(PermissionError):
        manager.approve(ticket.id, 'e1', 'send_message', params, owner_id='owner', device_id='d1', session_id='s2', destination=params['recipient'], data_classification='internal')
    with pytest.raises(PermissionError):
        manager.approve(ticket.id, 'e1', 'send_message', params, owner_id='attacker', device_id='d1', session_id='s1', destination=params['recipient'], data_classification='internal')
    assert manager.record(ticket.id)['status'] == 'pending'


def test_denial_is_durable_and_cannot_be_reapproved(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    manager = ApprovalManager(path=path)
    ticket, params = make_ticket(manager)
    assert manager.reject(ticket.id, device_id='d1', session_id='s1') is True
    assert ApprovalManager(path=path).record(ticket.id)['status'] == 'rejected'
    with pytest.raises(PermissionError):
        approve(ApprovalManager(path=path), ticket, params)


def test_expiry_boundary_is_terminal_and_does_not_create_fresh_approval(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    manager = ApprovalManager(ttl_seconds=30, path=path)
    ticket, params = make_ticket(manager)
    with pytest.raises(PermissionError, match='expired'):
        manager.approve(
            ticket.id, ticket.execution_id, ticket.tool_name, params,
            now=ticket.expires_at, owner_id='owner', device_id='d1', session_id='s1',
            destination=params['recipient'], data_classification='internal',
        )
    assert ApprovalManager(path=path).record(ticket.id)['status'] == 'expired'


def test_multiple_pending_approvals_remain_isolated(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    manager = ApprovalManager(path=path)
    a1, p1 = make_ticket(manager, execution='e1')
    a2, p2 = make_ticket(manager, execution='e2', params={'recipient': 'two@example.com', 'body': 'two'})
    a3, p3 = make_ticket(manager, execution='e3', params={'recipient': 'three@example.com', 'body': 'three'})
    approve(manager, a2, p2)
    assert manager.begin_dispatch(a2.id, worker_id='worker-a2')['dispatch'] is True
    manager.complete_dispatch(a2.id, {'status': 'completed', 'reply': 'two', 'verified': True})
    assert manager.record(a1.id)['status'] == 'pending'
    assert manager.record(a2.id)['status'] == 'completed'
    assert manager.record(a3.id)['status'] == 'pending'
    assert manager.context(a1.id)['execution_id'] == 'e1'
    assert manager.context(a3.id)['execution_id'] == 'e3'


def test_safe_pending_query_exposes_no_raw_parameters(tmp_path):
    manager = ApprovalManager(path=tmp_path / 'trusted-actions.sqlite3')
    ticket, _ = make_ticket(manager)
    rows = manager.list_pending(owner_id='owner', device_id='d1', session_id='s1')
    assert len(rows) == 1 and rows[0]['approval_id'] == ticket.id
    assert 'parameters' not in rows[0]
    assert 'payload_json' not in rows[0]


class _RelayMemory:
    def audit(self, *args):
        pass


class _RelayDevices:
    def is_active(self, device_id):
        return device_id == 'd1'

    def authorize(self, device_id, scope):
        return self.is_active(device_id) and scope == 'ai:chat'


class _RelaySessions:
    def emergency_stopped(self):
        return False


class _RelayEvents:
    def subscribe(self, *args):
        return lambda: None


class _RelayExecutor:
    def __init__(self, mode):
        self.mode = mode

    def approve(self, approval_id, **kwargs):
        if self.mode == 'dispatching':
            raise ApprovalDispatchInProgress('busy')
        if self.mode == 'recovery':
            raise ApprovalRecoveryRequired('uncertain')
        if self.mode == 'chained':
            raise ConfirmationRequired(
                'send_message', {'recipient': 'next@example.com'}, 'next step',
                approval_id='a2', execution_id='e1', expires_at=9999999999,
            )
        return 'done'

    def reject(self, approval_id, **kwargs):
        return 'rejected'


def _relay_for(mode):
    return SecureCloudRelay(
        executor=_RelayExecutor(mode), memory=_RelayMemory(), second_brain=None,
        device_registry=_RelayDevices(), sessions=_RelaySessions(), owner=SimpleNamespace(verify=lambda _: True),
        events=_RelayEvents(),
    )


def test_cloud_approval_transport_preserves_in_progress_recovery_and_chained_states():
    session = SimpleNamespace(device_id='d1', id='s1', reauthenticated_at=None)
    busy = _relay_for('dispatching').approval(session, 'a1', 'approve')
    assert busy.status == 409 and busy.payload['error'] == 'approval_in_progress'
    recovery = _relay_for('recovery').approval(session, 'a1', 'approve')
    assert recovery.status == 409 and recovery.payload['error'] == 'approval_recovery_required'
    chained = _relay_for('chained').approval(session, 'a1', 'approve')
    assert chained.status == 202
    assert chained.payload['approval_id'] == 'a2'
    assert chained.payload['prior_approval_id'] == 'a1'


class _PwaRegistry:
    def is_active(self, device_id):
        return device_id == 'd1'

    def authorize(self, device_id, scope):
        return device_id == 'd1' and scope == 'ai:chat'


class _PwaAgent:
    def approval_result(self, approval_id):
        if approval_id == 'a1':
            return {'approval_id': 'a1', 'status': 'pending', 'device_id': 'd1', 'session_id': 's1', 'outcome': None}
        return None

    def pending_approvals_safe(self, **kwargs):
        return []


class _PwaExecutor:
    def approve(self, approval_id):
        raise ConfirmationRequired(
            'send_message', {'recipient': 'next@example.com'}, 'next step',
            approval_id='a2', execution_id='e1', expires_at=9999999999,
        )

    def reject(self, approval_id):
        return 'Action cancelled.'


def test_pwa_approval_transport_returns_next_canonical_approval_instead_of_500():
    router = approval_router({'device_registry': _PwaRegistry(), 'agent_executor': _PwaAgent()}, _PwaExecutor())
    endpoint = next(
        route.endpoint for route in router.routes
        if route.path == '/iphone/api/approval/{approval_id}/approve' and 'POST' in route.methods
    )
    token = set_trusted_request(TrustedRequestContext(device_id='d1', session_id='s1'))
    try:
        response = endpoint('a1')
    finally:
        reset_trusted_request(token)
    assert response.status_code == 202
    payload = json.loads(response.body)
    assert payload['status'] == 'approval_required'
    assert payload['prior_approval_id'] == 'a1'
    assert payload['approval']['id'] == 'a2'
