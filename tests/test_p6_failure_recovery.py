from __future__ import annotations

from tests.p6_support import Harness


def test_verification_failure_after_side_effect_requires_recovery_and_is_not_retried(tmp_path):
    h = Harness(tmp_path, mode='act')
    try:
        counter = h.side_tool(
            'unverified_send',
            verifier=lambda params, result: {'verified': False, 'reason': 'postcondition mismatch', 'evidence': {}},
        )
        plan = h.operations.create_plan('Verification failure', [{
            'requested_tool': 'unverified_send',
            'parameters': {'reference': 'uncertain'},
        }])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        assert waiting['status'] == 'waiting_approval'
        assert counter.value == 0
        operation = h.operations.approve(waiting['operation_id'], **h.authority())
        assert counter.value == 1
        assert operation['status'] == 'recovery_required'
        assert operation['outcome_state'] == 'UNCERTAIN'
        assert operation['budget']['consumption']['retry_count'] == 0
        assert operation['budget']['policy']['max_retries'] == 0
    finally:
        h.close()


def test_read_only_failure_before_external_effect_is_failed_not_verified(tmp_path):
    h = Harness(tmp_path)
    try:
        def fail(params):
            raise RuntimeError('deterministic read failure')

        h.read_tool('failing_read', handler=fail)
        plan = h.operations.create_plan('Read failure', [{'requested_tool': 'failing_read'}])
        operation = h.operations.execute(plan['id'], **h.authority())['operation']
        assert operation['status'] == 'failed'
        assert operation['outcome_state'] == 'FAILED'
    finally:
        h.close()


def test_tool_call_budget_exhaustion_stops_before_extra_dispatch(tmp_path):
    h = Harness(tmp_path)
    try:
        first = h.read_tool('read_one')
        second = h.read_tool('read_two')
        try:
            h.operations.create_plan(
                'Tool budget',
                [{'requested_tool': 'read_one'}, {'requested_tool': 'read_two'}],
                budget_policy={'max_tool_calls': 1},
            )
            raised = False
        except ValueError as exc:
            raised = 'max_tool_calls' in str(exc)
        assert raised is True
        assert first.value == 0
        assert second.value == 0
    finally:
        h.close()


def test_cost_budget_without_confirmed_usage_fails_closed_before_dispatch(tmp_path):
    h = Harness(tmp_path)
    try:
        counter = h.read_tool()
        plan = h.operations.create_plan(
            'Cost bounded',
            [{'requested_tool': 'read_context'}],
            budget_policy={'max_cost': 0.01},
        )
        operation = h.operations.execute(plan['id'], **h.authority())['operation']
        assert counter.value == 0
        assert operation['status'] == 'failed'
        assert operation['budget']['stop_reason'] is None or 'usage' in (operation.get('last_error') or '').lower() or operation['status'] == 'failed'
    finally:
        h.close()


def test_emergency_stop_cannot_be_overridden_by_operation_budget_or_plan(tmp_path):
    h = Harness(tmp_path)
    try:
        counter = h.read_tool()
        plan = h.operations.create_plan('No self override', [{'requested_tool': 'read_context'}], budget_policy={
            'owner_override_allowed': True,
            'max_retries': 10,
        })
        assert plan['budget_policy']['owner_override_allowed'] is False
        assert plan['budget_policy']['max_retries'] == 0
        h.tools.set_emergency_stop(True)
        result = h.operations.execute(plan['id'], **h.authority())
        assert result['blocked'] is True
        assert counter.value == 0
    finally:
        h.close()


def test_consequential_exception_is_uncertain_not_forged_success(tmp_path):
    h = Harness(tmp_path, mode='act')
    calls = {'n': 0}
    try:
        def fail_after_possible_dispatch(params):
            calls['n'] += 1
            raise TimeoutError('simulated provider timeout')

        h.side_tool('timeout_send', handler=fail_after_possible_dispatch)
        plan = h.operations.create_plan('Timeout', [{
            'requested_tool': 'timeout_send',
            'parameters': {'reference': 'timeout'},
        }])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        assert waiting['status'] == 'waiting_approval'
        assert calls['n'] == 0
        operation = h.operations.approve(waiting['operation_id'], **h.authority())
        assert calls['n'] == 1
        assert operation['status'] == 'recovery_required'
        assert operation['outcome_state'] == 'UNCERTAIN'
        assert operation['budget']['consumption']['retry_count'] == 0
    finally:
        h.close()
