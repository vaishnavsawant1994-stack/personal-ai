from __future__ import annotations

import time
import pytest

from desktop.operator_context import current_operator_request
from tests.p6_support import Harness
from tools.registry import Risk, Tool


def test_p6_gate_blocks_until_external_trust_proof(tmp_path):
    h = Harness(tmp_path, qualified=False)
    try:
        h.read_tool()
        plan = h.operations.create_plan('Read safely', [{'requested_tool': 'read_context'}])
        result = h.operations.execute(plan['id'], **h.authority())
        assert result['blocked'] is True
        assert 'p3.permissions' in result['reason']
        with pytest.raises(ValueError):
            h.gate.record_external_proof('p3.permissions', True, source='model')
    finally:
        h.close()


def test_safe_read_only_work_is_really_delegated_and_verified(tmp_path):
    h = Harness(tmp_path)
    try:
        counter = h.read_tool()
        plan = h.operations.create_plan('Inspect deterministic context', [
            {'requested_tool': 'read_context', 'parameters': {'value': 'fixture'}}
        ])
        result = h.operations.execute(plan['id'], **h.authority())
        operation = result['operation']
        assert result['delegated'] is True
        assert operation['status'] == 'verified'
        assert operation['outcome_state'] == 'VERIFIED'
        assert counter.value == 1
        assert h.models.plan_calls == 0
        assert h.operations.plan(plan['id'])['steps'][0]['status'] == 'verified'
    finally:
        h.close()


def test_step_classification_uses_existing_tool_risk_and_cannot_be_downgraded(tmp_path):
    h = Harness(tmp_path)
    try:
        h.side_tool('verified_side')
        plan = h.operations.create_plan('Classify', [{
            'requested_tool': 'verified_side',
            'risk': 'READ_ONLY',
            'consequential': False,
            'parameters': {'reference': 'fixture'},
        }])
        step = plan['steps'][0]
        assert step['risk'] == 'EXTERNAL_SIDE_EFFECT'
        assert step['consequential'] is True
        assert step['approval_required'] is True
        assert step['expected_verification'] == 'required'
    finally:
        h.close()


def test_unavailable_prohibited_and_unverified_side_effect_tools_fail_closed(tmp_path):
    h = Harness(tmp_path)
    try:
        with pytest.raises(ValueError):
            h.operations.create_plan('Missing', [{'requested_tool': 'not_registered'}])
        h.read_tool('blocked', prohibited=True)
        with pytest.raises(PermissionError):
            h.operations.create_plan('Blocked', [{'requested_tool': 'blocked'}])
        h.side_tool('legacy_side', verification_required=False)
        with pytest.raises(PermissionError):
            h.operations.create_plan('Unsafe legacy', [{'requested_tool': 'legacy_side'}])
    finally:
        h.close()


def test_raw_secret_bearing_parameters_are_not_persistable(tmp_path):
    h = Harness(tmp_path)
    try:
        h.read_tool()
        with pytest.raises(ValueError):
            h.operations.create_plan('No raw secret', [{
                'requested_tool': 'read_context',
                'parameters': {'api_key': 'must-not-be-stored'},
            }])
        plan = h.operations.create_plan('Reference is allowed', [{
            'requested_tool': 'read_context',
            'parameters': {'credential_ref': 'vault:item-1'},
        }])
        assert plan['steps'][0]['parameters']['credential_ref'] == 'vault:item-1'
    finally:
        h.close()


def test_trusted_operator_context_is_propagated_without_p6_minting_authority(tmp_path):
    h = Harness(tmp_path)
    seen = {}
    try:
        def handler(params):
            ctx = current_operator_request()
            seen.update({'ctx': ctx, 'trusted': dict(params.get('_trusted_context') or {})})
            return {'ok': True}

        h.tools.register(Tool(
            'trusted_read',
            'read requiring existing trusted operator context',
            handler,
            Risk.READ_ONLY,
            requires_trusted_context=True,
        ))
        plan = h.operations.create_plan('Trusted read', [{'requested_tool': 'trusted_read'}])
        operation = h.operations.execute(plan['id'], **h.authority())['operation']
        assert operation['status'] == 'verified'
        assert seen['ctx'].owner_id == 'owner'
        assert seen['ctx'].device_id == 'device-1'
        assert seen['ctx'].session_id == 'session-1'
        assert seen['trusted']['security_epoch'] == h.executor.approvals.current_security_epoch()
    finally:
        h.close()


def test_required_reauthentication_is_checked_before_any_plan_step_dispatch(tmp_path):
    h = Harness(tmp_path, mode='act')
    try:
        read_counter = h.read_tool('prep')
        side_counter = h.side_tool('critical_step', requires_reauth=True, risk=Risk.CRITICAL)
        plan = h.operations.create_plan('Reauth first', [
            {'requested_tool': 'prep'},
            {'requested_tool': 'critical_step', 'parameters': {'reference': 'x'}},
        ])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        assert waiting['status'] == 'waiting_reauth'
        assert read_counter.value == 0
        assert side_counter.value == 0
        fresh = time.time()
        resumed = h.operations.execute(plan['id'], **h.authority(reauthenticated_at=fresh))
        assert resumed['duplicate'] is True
        assert resumed['operation']['status'] in {'waiting_approval', 'verified'}
        assert read_counter.value == 1
    finally:
        h.close()


def test_emergency_stop_blocks_before_delegation(tmp_path):
    h = Harness(tmp_path)
    try:
        h.read_tool()
        plan = h.operations.create_plan('Blocked by stop', [{'requested_tool': 'read_context'}])
        h.tools.set_emergency_stop(True)
        result = h.operations.execute(plan['id'], **h.authority())
        assert result['blocked'] is True
        assert 'emergency stop' in result['reason']
    finally:
        h.close()


def test_emergency_stop_between_steps_prevents_new_external_action(tmp_path):
    h = Harness(tmp_path)
    try:
        def stop_after_read(params):
            h.tools.set_emergency_stop(True)
            return {'stopped': True}

        h.read_tool('read_then_stop', handler=stop_after_read)
        side = h.side_tool('must_not_send')
        plan = h.operations.create_plan('Stop between steps', [
            {'requested_tool': 'read_then_stop'},
            {'requested_tool': 'must_not_send', 'parameters': {'reference': 'never'}},
        ])
        operation = h.operations.execute(plan['id'], **h.authority())['operation']
        assert side.value == 0
        assert operation['status'] == 'recovery_required'
        assert operation['outcome_state'] == 'UNCERTAIN'
    finally:
        h.close()
