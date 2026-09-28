from __future__ import annotations

import pytest

from security.approvals import ApprovalManager


def test_durable_approval_and_continuation_survive_restart(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    first = ApprovalManager(300, path=path)
    ticket = first.create(
        'execution-1',
        'email_send',
        {'to': 'owner@example.com', 'body': 'hello'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
        destination='owner@example.com',
        data_classification='internal',
    )
    first.save_context(ticket.id, {'execution_id': 'execution-1', 'index': 0, 'device_id': 'device-1'})

    restarted = ApprovalManager(300, path=path)
    restored = restarted.ticket(ticket.id)

    assert restored is not None
    assert restored.device_id == 'device-1'
    assert restored.session_id == 'session-1'
    assert restarted.context(ticket.id) == {
        'execution_id': 'execution-1',
        'index': 0,
        'device_id': 'device-1',
    }


def test_approval_is_bound_to_device_session_destination_and_classification(tmp_path):
    approvals = ApprovalManager(300, path=tmp_path / 'trusted-actions.sqlite3')
    parameters = {'to': 'person@example.com', 'body': 'hello'}
    ticket = approvals.create(
        'execution-1',
        'email_send',
        parameters,
        device_id='device-1',
        session_id='session-1',
        destination='person@example.com',
        data_classification='sensitive',
    )

    with pytest.raises(PermissionError, match='device'):
        approvals.consume(
            ticket.id,
            'execution-1',
            'email_send',
            parameters,
            owner_id='owner',
            device_id='device-2',
            session_id='session-1',
            destination='person@example.com',
            data_classification='sensitive',
        )

    with pytest.raises(PermissionError, match='session'):
        approvals.consume(
            ticket.id,
            'execution-1',
            'email_send',
            parameters,
            owner_id='owner',
            device_id='device-1',
            session_id='session-2',
            destination='person@example.com',
            data_classification='sensitive',
        )

    with pytest.raises(PermissionError, match='destination'):
        approvals.consume(
            ticket.id,
            'execution-1',
            'email_send',
            parameters,
            owner_id='owner',
            device_id='device-1',
            session_id='session-1',
            destination='attacker@example.com',
            data_classification='sensitive',
        )

    with pytest.raises(PermissionError, match='classification'):
        approvals.consume(
            ticket.id,
            'execution-1',
            'email_send',
            parameters,
            owner_id='owner',
            device_id='device-1',
            session_id='session-1',
            destination='person@example.com',
            data_classification='secret',
        )

    # Failed scope checks do not broaden or mutate the original permit.
    assert approvals.ticket(ticket.id) is not None


def test_parameter_tampering_does_not_consume_valid_ticket(tmp_path):
    approvals = ApprovalManager(300, path=tmp_path / 'trusted-actions.sqlite3')
    ticket = approvals.create('execution-1', 'tool', {'value': 7})

    with pytest.raises(PermissionError, match='scope'):
        approvals.consume(ticket.id, 'execution-1', 'tool', {'value': 999})

    approvals.consume(ticket.id, 'execution-1', 'tool', {'value': 7})
    with pytest.raises(PermissionError, match='already used'):
        approvals.consume(ticket.id, 'execution-1', 'tool', {'value': 7})


def test_one_use_consumption_is_atomic_across_manager_instances(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    first = ApprovalManager(300, path=path)
    second = ApprovalManager(300, path=path)
    ticket = first.create('execution-1', 'tool', {'value': 7})

    first.consume(ticket.id, 'execution-1', 'tool', {'value': 7})
    with pytest.raises(PermissionError, match='already used'):
        second.consume(ticket.id, 'execution-1', 'tool', {'value': 7})


def test_security_epoch_invalidates_all_pending_approvals(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    approvals = ApprovalManager(300, path=path)
    ticket = approvals.create('execution-1', 'tool', {'value': 7})
    approvals.save_context(ticket.id, {'execution_id': 'execution-1'})

    new_epoch = approvals.advance_security_epoch()

    assert new_epoch == 1
    assert approvals.ticket(ticket.id) is None
    assert approvals.context(ticket.id) is None
    with pytest.raises(PermissionError):
        approvals.consume(ticket.id, 'execution-1', 'tool', {'value': 7})


def test_reject_is_scope_bound_and_durable(tmp_path):
    path = tmp_path / 'trusted-actions.sqlite3'
    approvals = ApprovalManager(300, path=path)
    ticket = approvals.create(
        'execution-1',
        'tool',
        {'value': 7},
        device_id='device-1',
        session_id='session-1',
    )

    with pytest.raises(PermissionError, match='device'):
        approvals.reject(ticket.id, device_id='device-2', session_id='session-1')
    assert approvals.reject(ticket.id, device_id='device-1', session_id='session-1') is True
    assert ApprovalManager(300, path=path).ticket(ticket.id) is None
