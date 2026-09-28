from __future__ import annotations

from datetime import datetime, timezone
import json

from memory.second_brain import MemoryCandidate
from tests.p6_support import Harness


def test_due_reminder_is_context_not_authority_and_never_auto_executes(tmp_path):
    h = Harness(tmp_path)
    try:
        counter = h.side_tool()
        item_id = h.everyday.add('commitment', 'Send the proposal', due_at='2020-01-01T00:00:00+00:00')
        h.everyday.refresh_due(now=datetime(2026, 9, 15, tzinfo=timezone.utc))
        assert h.everyday.get(item_id)['status'] == 'due'
        assert h.operations.operations(status='all') == []
        assert counter.value == 0
        plan = h.operations.create_from_everyday(item_id, 'Handle proposal', [{
            'requested_tool': 'send_action',
            'parameters': {'recipient': 'example.test', 'reference': 'proposal'},
        }])
        operation = h.operations.execute(plan['id'], **h.authority())['operation']
        assert operation['status'] == 'waiting_approval'
        assert counter.value == 0
        assert h.everyday.get(item_id)['status'] == 'due'
    finally:
        h.close()


def test_sensitive_memory_handoff_requires_existing_scope_and_never_copies_content_to_operation_view(tmp_path):
    h = Harness(tmp_path)
    try:
        h.read_tool()
        secret_text = 'Secret acquisition detail that must not enter operation logs'
        secret_id = h.second_brain.remember(MemoryCandidate(
            type='decision', subject='Private acquisition', content=secret_text,
            confidence=.95, source='explicit-user', sensitivity='secret', verified=True,
        ))
        try:
            h.operations.create_plan('Use secret context', [{'requested_tool': 'read_context'}], memory_ids=[secret_id])
            raised = False
        except PermissionError:
            raised = True
        assert raised is True
        plan = h.operations.create_plan(
            'Authorized secret reference',
            [{'requested_tool': 'read_context'}],
            memory_ids=[secret_id],
            allowed_sensitivities={'normal', 'secret'},
        )
        operation = h.operations.execute(plan['id'], **h.authority())['operation']
        payload = json.dumps(operation)
        audits = json.dumps(h.memory.audit_entries('personal-operations', 100))
        assert secret_text not in payload
        assert secret_text not in audits
        assert operation['plan']['memory_reference_count'] == 1
    finally:
        h.close()


def test_verified_outcome_updates_commitment_and_writes_safe_second_brain_event(tmp_path):
    h = Harness(tmp_path)
    try:
        h.read_tool('prepare')
        item_id = h.everyday.add('commitment', 'Prepare owner packet')
        plan = h.operations.create_from_everyday(item_id, 'Prepare packet', [{'requested_tool': 'prepare'}])
        operation = h.operations.execute(plan['id'], **h.authority())['operation']
        assert operation['status'] == 'verified'
        assert h.everyday.get(item_id)['status'] == 'completed'
        assert operation['outcome_memory_id']
        detail = h.second_brain.memory_detail(operation['outcome_memory_id'])
        assert bool(detail['verified']) is True
        assert detail['metadata_json'] if 'metadata_json' in detail else detail.get('metadata') is not None
        assert operation['operation_id'] in detail['content']
    finally:
        h.close()


def test_end_to_end_memory_commitment_preparation_approval_verification_and_completion(tmp_path):
    h = Harness(tmp_path)
    try:
        contact = h.second_brain.remember(MemoryCandidate(
            type='person', subject='John', content='John is the proposal contact.',
            confidence=.95, source='explicit-user', verified=True,
        ))
        item_id = h.everyday.add(
            'commitment', 'Send John the proposal', due_at='2020-01-01T00:00:00+00:00',
            related_memory_ids=[contact], evidence=[{'kind': 'conversation', 'id': 'conv-fixture'}],
        )
        h.read_tool('prepare_packet')
        sent = h.side_tool('send_packet')
        plan = h.operations.create_from_everyday(item_id, 'Handle John proposal', [
            {'requested_tool': 'prepare_packet'},
            {'requested_tool': 'send_packet', 'parameters': {'recipient': 'john.example', 'reference': 'proposal-v1'}},
        ])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        assert waiting['status'] == 'waiting_approval'
        assert waiting['current_step'] == 1
        assert sent.value == 0
        assert h.everyday.get(item_id)['status'] != 'completed'
        complete = h.operations.approve(waiting['operation_id'], **h.authority())
        assert sent.value == 1
        assert complete['status'] == 'verified'
        assert h.everyday.get(item_id)['status'] == 'completed'
        assert complete['outcome_memory_id']
        events = {event['event'] for event in h.event_log}
        assert {'future.operation.planning', 'future.operation.approval_required', 'future.operation.completed'} <= events
    finally:
        h.close()


def test_end_to_end_approval_denied_has_zero_consequential_side_effect(tmp_path):
    h = Harness(tmp_path)
    try:
        h.read_tool('prepare_packet')
        sent = h.side_tool('send_packet')
        item_id = h.everyday.add('commitment', 'Send denied packet')
        plan = h.operations.create_from_everyday(item_id, 'Denied scenario', [
            {'requested_tool': 'prepare_packet'},
            {'requested_tool': 'send_packet', 'parameters': {'recipient': 'deny.example', 'reference': 'v1'}},
        ])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        denied = h.operations.reject(waiting['operation_id'], **h.authority())
        assert denied['status'] == 'cancelled'
        assert sent.value == 0
        assert h.everyday.get(item_id)['status'] != 'completed'
    finally:
        h.close()


def test_end_to_end_verification_failure_requires_recovery_and_keeps_commitment_open(tmp_path):
    h = Harness(tmp_path, mode='act')
    try:
        h.read_tool('prepare_packet')
        side = h.side_tool(
            'send_packet',
            verifier=lambda params, result: {'verified': False, 'reason': 'simulated verification failure', 'evidence': {}},
        )
        item_id = h.everyday.add('commitment', 'Send uncertain packet')
        plan = h.operations.create_from_everyday(item_id, 'Recovery scenario', [
            {'requested_tool': 'prepare_packet'},
            {'requested_tool': 'send_packet', 'parameters': {'reference': 'uncertain'}},
        ])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        assert waiting['status'] == 'waiting_approval'
        assert side.value == 0
        operation = h.operations.approve(waiting['operation_id'], **h.authority())
        assert side.value == 1
        assert operation['status'] == 'recovery_required'
        assert operation['outcome_state'] == 'UNCERTAIN'
        assert h.everyday.get(item_id)['status'] != 'completed'
        assert 'future.operation.recovery_required' in {event['event'] for event in h.event_log}

        internal = h.operations._delegation(operation['operation_id'])
        class FakeW7Recovery:
            def __init__(self):
                self.state = 'recovery_review_required'
            def transaction_binding(self, transaction_id):
                assert transaction_id == 'tx-recovery-fixture'
                return {
                    'owner_id': internal['owner_id'], 'device_id': internal['device_id'],
                    'session_id': internal['session_id'], 'security_epoch': internal['security_epoch'],
                    'workflow_id': internal['operation_id'],
                }
            def owner_view(self, transaction_id):
                return {
                    'transaction_id': transaction_id,
                    'transaction_state': 'recovery_review_required' if self.state != 'compensated' else 'completed',
                    'recovery_state': self.state,
                    'verified': [], 'uncertain': [] if self.state == 'compensated' else [{'verification_id': 'uncertain-v1'}],
                    'rollback_limitations': ([{'compensation_id': 'cmp-1', 'state': 'compensated'}]
                                             if self.state == 'compensated' else []),
                }
        recovery = FakeW7Recovery()
        h.tools.ensure_recovery_authority = lambda: recovery
        linked = h.operations.attach_recovery(operation['operation_id'], 'tx-recovery-fixture', **h.authority())
        assert linked['status'] == 'recovery_required'
        pending = h.operations.refresh_recovery(operation['operation_id'], **h.authority())
        assert pending['status'] == 'recovery_required'
        recovery.state = 'compensated'
        recovered = h.operations.refresh_recovery(operation['operation_id'], **h.authority())
        assert recovered['status'] == 'recovered'
        assert recovered['outcome_state'] == 'RECOVERED'
        assert h.everyday.get(item_id)['status'] != 'completed'
    finally:
        h.close()
