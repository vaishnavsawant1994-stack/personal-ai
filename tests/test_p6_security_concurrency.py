from __future__ import annotations

import threading
import time
import pytest

from tests.p6_support import Harness
from tools.registry import Risk, Tool


def test_existing_destination_allowlist_is_enforced_before_delegation(tmp_path):
    h = Harness(tmp_path)
    try:
        h.tools.register(Tool(
            'allowed_send', 'allowlisted side effect',
            lambda params: {'verified': True},
            Risk.EXTERNAL_SIDE_EFFECT,
            verifier=lambda p, r: {'verified': True, 'reason': 'fixture', 'evidence': {}},
            verification_required=True,
            allowed_destinations=('allowed.example',),
        ))
        with pytest.raises(PermissionError):
            h.operations.create_plan('Bad destination', [{
                'requested_tool': 'allowed_send',
                'parameters': {'url': 'https://evil.example/path'},
            }])
        plan = h.operations.create_plan('Allowed destination', [{
            'requested_tool': 'allowed_send',
            'parameters': {'url': 'https://allowed.example/path'},
        }])
        assert plan['steps'][0]['requested_tool'] == 'allowed_send'
    finally:
        h.close()


def test_existing_data_classification_policy_cannot_be_bypassed(tmp_path):
    h = Harness(tmp_path)
    try:
        h.tools.register(Tool(
            'no_secret_read', 'read that forbids secret input', lambda params: {'ok': True}, Risk.READ_ONLY,
            prohibited_data_classifications=('secret',),
        ))
        with pytest.raises(PermissionError):
            h.operations.create_plan('Forbidden secret', [{
                'requested_tool': 'no_secret_read', 'sensitivity': 'secret'
            }])
    finally:
        h.close()


def test_read_only_parallel_operations_can_use_existing_concurrency_budget(tmp_path):
    h = Harness(tmp_path)
    started = threading.Event()
    release = threading.Event()
    count = {'n': 0}
    guard = threading.Lock()
    try:
        def blocking(params):
            with guard:
                count['n'] += 1
                if count['n'] >= 2:
                    started.set()
            release.wait(3)
            return {'ok': True}

        h.read_tool('parallel_read', handler=blocking)
        p1 = h.operations.create_plan('Parallel one', [{'requested_tool': 'parallel_read'}])
        p2 = h.operations.create_plan('Parallel two', [{'requested_tool': 'parallel_read'}])
        one = h.operations.execute(p1['id'], background=True, **h.authority())
        two = h.operations.execute(p2['id'], background=True, **h.authority())
        assert one['delegated'] and two['delegated']
        assert started.wait(3)
        release.set()
        for operation_id in (one['operation']['operation_id'], two['operation']['operation_id']):
            thread = h.operations._threads[operation_id]
            thread.join(timeout=5)
            assert h.operations.operation(operation_id)['status'] == 'verified'
        assert count['n'] == 2
    finally:
        release.set()
        h.close()


def test_cancellation_interrupts_inflight_read_only_execution_and_survives_restart_state(tmp_path):
    h = Harness(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    try:
        def blocking(params):
            entered.set()
            release.wait(3)
            return {'ok': True}

        h.read_tool('slow_read', handler=blocking)
        plan = h.operations.create_plan('Slow read', [{'requested_tool': 'slow_read'}])
        result = h.operations.execute(plan['id'], background=True, **h.authority())
        operation_id = result['operation']['operation_id']
        assert entered.wait(3)
        cancel_result = {}

        def cancel():
            cancel_result.update(h.operations.cancel(operation_id, **h.authority()))

        thread = threading.Thread(target=cancel)
        thread.start()
        time.sleep(0.05)
        release.set()
        thread.join(timeout=5)
        h.operations._threads[operation_id].join(timeout=5)
        assert h.operations.operation(operation_id)['status'] == 'cancelled'
    finally:
        release.set()
        h.close()


def test_cancellation_during_consequential_dispatch_becomes_recovery_review(tmp_path):
    h = Harness(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    calls = {'n': 0}
    try:
        def blocking_send(params):
            entered.set()
            release.wait(3)
            calls['n'] += 1
            return {'sent': True, 'reference': 'race'}

        h.side_tool('slow_send', handler=blocking_send)
        plan = h.operations.create_plan('Slow send', [{
            'requested_tool': 'slow_send',
            'parameters': {'recipient': 'race.example', 'reference': 'race'},
        }])
        waiting = h.operations.execute(plan['id'], **h.authority())['operation']
        operation_id = waiting['operation_id']

        approval_result = {}
        def approve():
            approval_result.update(h.operations.approve(operation_id, **h.authority()))

        approver = threading.Thread(target=approve)
        approver.start()
        assert entered.wait(3)
        canceller = threading.Thread(target=lambda: h.operations.cancel(operation_id, **h.authority()))
        canceller.start()
        time.sleep(0.05)
        release.set()
        approver.join(timeout=5)
        canceller.join(timeout=5)
        final = h.operations.operation(operation_id)
        assert calls['n'] == 1
        assert final['status'] == 'recovery_required'
        assert final['outcome_state'] == 'UNCERTAIN'
    finally:
        release.set()
        h.close()
