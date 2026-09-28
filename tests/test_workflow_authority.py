from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agent.executor import AgentExecutor, ConfirmationRequired
from automation.engine import AutomationEngine
from core.events import EventBus
from memory.store import MemoryStore
from tools.registry import Risk, Tool, ToolRegistry


class CapturingExecutor:
    def __init__(self):
        self.calls = []

    def chat(self, prompt, **kwargs):
        self.calls.append(('chat', prompt, kwargs))
        return f'done:{prompt}'


class ApprovalExecutor(CapturingExecutor):
    def chat(self, prompt, **kwargs):
        self.calls.append(('chat', prompt, kwargs))
        raise ConfirmationRequired(
            'email.send',
            {'recipient': 'owner@example.com'},
            approval_id='approval-1',
            execution_id='execution-1',
            expires_at=time.time() + 300,
        )

    def approve(self, approval_id, **kwargs):
        self.calls.append(('approve', approval_id, kwargs))
        return 'sent'

    def reject(self, approval_id, **kwargs):
        self.calls.append(('reject', approval_id, kwargs))
        return 'cancelled'


def create_prompt_workflow(engine):
    return engine.create_workflow(
        'Bound workflow',
        {'type': 'manual'},
        [{'kind': 'prompt', 'prompt': 'perform action', 'retries': 0}],
    )


def test_workflow_persists_and_propagates_initiating_authority(tmp_path):
    executor = CapturingExecutor()
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=executor)
    workflow_id = create_prompt_workflow(engine)

    run_id = engine.run_workflow(
        workflow_id,
        background=False,
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
        reauthenticated_at=123.0,
    )

    run = engine._run(run_id)
    assert (run['owner_id'], run['device_id'], run['session_id']) == (
        'owner', 'device-1', 'session-1'
    )
    assert run['reauthenticated_at'] == 123.0
    assert executor.calls[0][2] == {
        'cancel_event': executor.calls[0][2]['cancel_event'],
        'owner_id': 'owner',
        'device_id': 'device-1',
        'session_id': 'session-1',
        'reauthenticated_at': 123.0,
    }
    assert 'session_id' not in engine.runs()[0]
    assert 'reauthenticated_at' not in engine.runs()[0]


def test_workflow_approval_rejects_other_device_or_session(tmp_path):
    executor = ApprovalExecutor()
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=executor)
    run_id = engine.run_workflow(
        create_prompt_workflow(engine),
        background=False,
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    assert engine._run(run_id)['status'] == 'waiting_approval'

    with pytest.raises(PermissionError, match='device identity mismatch'):
        engine.approve_run(
            run_id, 'approval-1', owner_id='owner', device_id='device-2', session_id='session-1'
        )
    with pytest.raises(PermissionError, match='session identity mismatch'):
        engine.approve_run(
            run_id, 'approval-1', owner_id='owner', device_id='device-1', session_id='session-2'
        )

    result = engine.approve_run(
        run_id,
        'approval-1',
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
        reauthenticated_at=456.0,
    )
    assert result['resumed'] is True
    approve_call = next(call for call in executor.calls if call[0] == 'approve')
    assert approve_call[2]['device_id'] == 'device-1'
    assert approve_call[2]['session_id'] == 'session-1'
    assert approve_call[2]['reauthenticated_at'] == 456.0


def test_bound_workflow_mutations_require_initiating_identity(tmp_path):
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=CapturingExecutor())
    workflow_id = engine.create_workflow(
        'Recoverable', {'type': 'manual'}, [{'kind': 'set', 'key': 'ok', 'value': True}]
    )
    run_id = engine.run_workflow(
        workflow_id,
        background=False,
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )

    with pytest.raises(PermissionError, match='device identity mismatch'):
        engine.cancel_run(
            run_id, owner_id='owner', device_id='device-2', session_id='session-1'
        )


class Models:
    def chat(self, *_args, **_kwargs):
        return 'completed'


class Planner:
    def plan(self, *_args, **_kwargs):
        return {
            'steps': [{
                'tool': 'dangerous',
                'parameters': {'destination': 'example.com'},
                'description': 'perform exact action',
            }]
        }


def durable_executor(tmp_path, calls):
    registry = ToolRegistry(SimpleNamespace(autonomy_mode='ask', data_dir=tmp_path))
    registry.register(Tool(
        'dangerous',
        'external action',
        lambda params: calls.append(dict(params)) or {'verified': True},
        Risk.EXTERNAL_SIDE_EFFECT,
    ))
    executor = AgentExecutor(
        models=Models(),
        tools=registry,
        memory=MemoryStore(tmp_path / 'assistant.sqlite3'),
        events=EventBus(),
    )
    executor.planner = Planner()
    return executor


def test_session_bound_workflow_approval_survives_engine_and_executor_restart(tmp_path):
    calls = []
    first = AutomationEngine(
        tmp_path / 'workflows.sqlite3', executor=durable_executor(tmp_path, calls)
    )
    run_id = first.run_workflow(
        create_prompt_workflow(first),
        background=False,
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    approval_id = first._run(run_id)['pending_approval_id']

    restarted = AutomationEngine(
        tmp_path / 'workflows.sqlite3', executor=durable_executor(tmp_path, calls)
    )
    assert restarted._run(run_id)['status'] == 'waiting_approval'
    with pytest.raises(PermissionError, match='session identity mismatch'):
        restarted.approve_run(
            run_id,
            approval_id,
            owner_id='owner',
            device_id='device-1',
            session_id='session-2',
        )

    restarted.approve_run(
        run_id,
        approval_id,
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    for _ in range(100):
        if restarted._run(run_id)['status'] == 'completed':
            break
        time.sleep(.01)

    assert restarted._run(run_id)['status'] == 'completed'
    assert calls == [{'destination': 'example.com'}]


def test_stage8_device_revocation_cancels_only_bound_workflows(tmp_path):
    executor = ApprovalExecutor()
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=executor)
    workflow_id = create_prompt_workflow(engine)
    first = engine.run_workflow(
        workflow_id, background=False, owner_id='owner', device_id='device-1', session_id='session-1'
    )
    second = engine.run_workflow(
        workflow_id, background=False, owner_id='owner', device_id='device-2', session_id='session-2'
    )
    assert engine._run(first)['status'] == 'waiting_approval'
    assert engine._run(second)['status'] == 'waiting_approval'

    assert engine.cancel_device_runs('device-1', reason='device_revoked') == 1

    assert engine._run(first)['status'] == 'cancelled'
    assert engine._run(first)['error'] == 'device_revoked'
    assert engine._run(second)['status'] == 'waiting_approval'


def test_stage8_session_revocation_cancels_only_bound_workflows(tmp_path):
    executor = ApprovalExecutor()
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=executor)
    workflow_id = create_prompt_workflow(engine)
    first = engine.run_workflow(
        workflow_id, background=False, owner_id='owner', device_id='device-1', session_id='session-1'
    )
    second = engine.run_workflow(
        workflow_id, background=False, owner_id='owner', device_id='device-1', session_id='session-2'
    )

    assert engine.cancel_session_runs('session-1', reason='session_revoked') == 1

    assert engine._run(first)['status'] == 'cancelled'
    assert engine._run(first)['error'] == 'session_revoked'
    assert engine._run(second)['status'] == 'waiting_approval'
