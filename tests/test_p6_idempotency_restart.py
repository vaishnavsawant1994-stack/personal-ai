from __future__ import annotations

from future_intelligence.operations import PersonalOperations
from tests.p6_support import Harness


def test_duplicate_plan_execute_does_not_duplicate_consequential_dispatch(tmp_path):
    h = Harness(tmp_path)
    try:
        counter = h.side_tool()
        plan = h.operations.create_plan('One send', [{
            'requested_tool': 'send_action',
            'parameters': {'recipient': 'example.test', 'reference': 'one'},
        }])
        first = h.operations.execute(plan['id'], **h.authority())
        second = h.operations.execute(plan['id'], **h.authority())
        assert first['operation']['operation_id'] == second['operation']['operation_id']
        assert second['duplicate'] is True
        assert counter.value == 0
        h.operations.approve(first['operation']['operation_id'], **h.authority())
        assert counter.value == 1
        third = h.operations.execute(plan['id'], **h.authority())
        assert third['duplicate'] is True
        assert third['operation']['status'] == 'verified'
        assert counter.value == 1
    finally:
        h.close()


def test_restart_while_executing_becomes_recovery_required_not_auto_replay(tmp_path):
    h = Harness(tmp_path)
    try:
        counter = h.read_tool()
        plan = h.operations.create_plan('Interrupted', [{'requested_tool': 'read_context'}])
        operation, _ = h.operations._insert_operation(plan, owner_id='owner', device_id='device-1', session_id='session-1', security_epoch=h.operations._security_epoch())
        h.operations._update_operation(operation['operation_id'], status='executing', outcome_state='DISPATCHED')
        restarted = PersonalOperations(
            gate=h.gate,
            executor=h.executor,
            automations=h.automations,
            events=h.events,
            second_brain=h.second_brain,
            memory=h.memory,
            everyday=h.everyday,
            path=tmp_path / 'future-intelligence' / 'operations.sqlite3',
        )
        recovered = restarted.operation(operation['operation_id'])
        assert recovered['status'] == 'recovery_required'
        assert recovered['outcome_state'] == 'UNCERTAIN'
        assert counter.value == 0
    finally:
        h.close()


def test_waiting_approval_survives_p6_and_executor_memory_restart(tmp_path):
    h = Harness(tmp_path)
    try:
        counter = h.side_tool()
        plan = h.operations.create_plan('Durable approval', [{
            'requested_tool': 'send_action',
            'parameters': {'recipient': 'example.test', 'reference': 'durable'},
        }])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        h.executor._paused.clear()
        restarted = PersonalOperations(
            gate=h.gate,
            executor=h.executor,
            automations=h.automations,
            events=h.events,
            second_brain=h.second_brain,
            memory=h.memory,
            everyday=h.everyday,
            path=tmp_path / 'future-intelligence' / 'operations.sqlite3',
        )
        assert restarted.operation(waiting['operation_id'])['status'] == 'waiting_approval'
        approved = restarted.approve(waiting['operation_id'], **h.authority())
        assert approved['status'] == 'verified'
        assert counter.value == 1
    finally:
        h.close()


def test_owner_cancellation_waiting_approval_rejects_existing_ticket_and_persists(tmp_path):
    h = Harness(tmp_path)
    try:
        counter = h.side_tool()
        plan = h.operations.create_plan('Cancel me', [{
            'requested_tool': 'send_action',
            'parameters': {'recipient': 'example.test', 'reference': 'cancel'},
        }])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        cancelled = h.operations.cancel(waiting['operation_id'], **h.authority())
        assert cancelled['status'] == 'cancelled'
        assert counter.value == 0
        restarted = PersonalOperations(
            gate=h.gate,
            executor=h.executor,
            automations=h.automations,
            events=h.events,
            second_brain=h.second_brain,
            memory=h.memory,
            everyday=h.everyday,
            path=tmp_path / 'future-intelligence' / 'operations.sqlite3',
        )
        assert restarted.operation(waiting['operation_id'])['status'] == 'cancelled'
        assert counter.value == 0
    finally:
        h.close()


def test_two_active_consequential_operations_same_destination_are_serialized(tmp_path):
    h = Harness(tmp_path)
    try:
        first_counter = h.side_tool('send_one')
        second_counter = h.side_tool('send_two')
        p1 = h.operations.create_plan('First', [{
            'requested_tool': 'send_one', 'parameters': {'recipient': 'same.example', 'reference': '1'}
        }])
        p2 = h.operations.create_plan('Second', [{
            'requested_tool': 'send_two', 'parameters': {'recipient': 'same.example', 'reference': '2'}
        }])
        first = h.operations.execute(p1['id'], **h.authority())['operation']
        assert first['status'] == 'waiting_approval'
        try:
            h.operations.execute(p2['id'], **h.authority())
            raised = False
        except RuntimeError:
            raised = True
        assert raised is True
        assert first_counter.value == 0
        assert second_counter.value == 0
    finally:
        h.close()


def test_same_commitment_cannot_have_two_active_operations(tmp_path):
    h = Harness(tmp_path)
    try:
        h.side_tool('send_one')
        h.side_tool('send_two')
        item = h.everyday.add('commitment', 'Send proposal')
        p1 = h.operations.create_from_everyday(item, 'First', [{
            'requested_tool': 'send_one', 'parameters': {'recipient': 'one.example', 'reference': '1'}
        }])
        h.operations.execute(p1['id'], **h.authority())
        try:
            h.operations.create_from_everyday(item, 'Second', [{
                'requested_tool': 'send_two', 'parameters': {'recipient': 'two.example', 'reference': '2'}
            }])
            raised = False
        except RuntimeError:
            raised = True
        assert raised is True
    finally:
        h.close()
