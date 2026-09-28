from __future__ import annotations

from types import SimpleNamespace

import threading
import time
import pytest

from activities.projection import ActivitiesProjection
from agent.executor import ExecutionCancelled
from core.personal_ai_runtime import CanonicalTurnRuntime, TurnReplayBlocked
from devices.continuity import ContinuityService


RID = '550e8400-e29b-41d4-a716-446655440000'
RID2 = '123e4567-e89b-42d3-a456-426614174000'
MULTISTEP = 'Research these companies, then verify them and prepare a report.'


class Executor:
    def __init__(self, *, fail=False, audit=None):
        self.approvals = SimpleNamespace(current_security_epoch=lambda: 0)
        self.calls = 0
        self.fail = fail
        self.audit = audit

    def chat(self, text, **kwargs):
        self.calls += 1
        if self.audit is not None:
            self.audit.rows.append({
                'id': f'activity-{self.calls}',
                'category': 'agent',
                'action': 'completed',
                'created_at': 'now',
                'payload': {'request_id': kwargs.get('request_id'), 'ok': True},
            })
        if self.fail:
            raise RuntimeError('deterministic failure')
        return f'answer:{text}'


class AuditStore:
    def __init__(self):
        self.rows = []

    def audit_entries(self, *, category=None, limit=100):
        rows = self.rows if category is None else [row for row in self.rows if row['category'] == category]
        return rows[-limit:]


class CompletedAutonomy:
    def __init__(self):
        self.goals = []
        self.plans = []
        self.executed = []

    def create_goal(self, text, **kwargs):
        goal = {'id': 'g1', 'description': text}
        self.goals.append((goal, kwargs))
        return goal

    def propose_plan_with_model(self, goal_id, **kwargs):
        plan = {'id': 'p1', 'goal_id': goal_id, 'state': 'READY', 'tasks': [{'id': 't1', 'status': 'WAITING'}]}
        self.plans.append(plan)
        return plan

    def ready_tasks(self, plan_id, **kwargs):
        return [task for task in self.plans[-1]['tasks'] if task['status'] == 'WAITING']

    def execute_task(self, plan_id, task_id, **kwargs):
        self.executed.append((plan_id, task_id))
        plan = self.plans[-1]
        plan['tasks'][0]['status'] = 'COMPLETED'
        plan['state'] = 'COMPLETED'
        return plan

    def plan(self, plan_id, **kwargs):
        return self.plans[-1]


class WaitingApprovalAutonomy(CompletedAutonomy):
    def execute_task(self, plan_id, task_id, **kwargs):
        self.executed.append((plan_id, task_id))
        plan = self.plans[-1]
        task = plan['tasks'][0]
        task.update({
            'status': 'WAITING_APPROVAL',
            'approval_ref': 'a1',
            'requested_tool': 'send_message',
            'operation_id': 'o1',
        })
        plan['state'] = 'WAITING_APPROVAL'
        return plan


def runtime(tmp_path, executor=None):
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3')
    lower = executor or Executor()
    return CanonicalTurnRuntime(lower, continuity, tmp_path / 'turns.sqlite3'), continuity, lower


def test_new_intentional_turn_uses_new_request_and_executes_once_each(tmp_path):
    turn_runtime, _, lower = runtime(tmp_path)
    assert turn_runtime.chat('first', request_id=RID, device_id='d1') == 'answer:first'
    assert turn_runtime.chat('second', request_id=RID2, device_id='d1') == 'answer:second'
    assert lower.calls == 2
    assert turn_runtime.turn(RID)['status'] == 'completed'
    assert turn_runtime.turn(RID2)['status'] == 'completed'


def test_failed_request_transport_retry_does_not_restart_failed_logical_turn(tmp_path):
    lower = Executor(fail=True)
    turn_runtime, continuity, _ = runtime(tmp_path, lower)
    with pytest.raises(RuntimeError, match='deterministic failure'):
        turn_runtime.chat('fail once', request_id=RID, device_id='d1')
    assert turn_runtime.turn(RID)['status'] == 'failed'
    with pytest.raises(TurnReplayBlocked, match='failed'):
        turn_runtime.chat('fail once', request_id=RID, device_id='d1')
    assert lower.calls == 1
    thread = continuity.active_for_device('d1')
    assert [event['kind'] for event in continuity.events_for_thread(thread['id'])] == ['user_message']


def test_p10_completed_result_replay_after_lost_transport_does_not_replan_or_reexecute(tmp_path):
    turn_runtime, continuity, lower = runtime(tmp_path)
    autonomy = CompletedAutonomy()
    turn_runtime.attach_autonomy(autonomy)
    # The caller intentionally discards the first returned result, modelling an
    # HTTP response that was lost after the canonical result became durable.
    turn_runtime.chat(MULTISTEP, request_id=RID, device_id='d1', session_id='s1')
    replay = turn_runtime.chat(MULTISTEP, request_id=RID, device_id='d1', session_id='s1')
    assert 'Orchestration completed' in replay
    assert lower.calls == 0
    assert len(autonomy.goals) == 1
    assert len(autonomy.plans) == 1
    assert autonomy.executed == [('p1', 't1')]
    turn = turn_runtime.turn(RID)
    assert turn['p10_goal_id'] == 'g1' and turn['p10_plan_id'] == 'p1'
    thread = continuity.active_for_device('d1')
    assert [event['kind'] for event in continuity.events_for_thread(thread['id'])] == ['user_message', 'assistant_message']


def test_p10_waiting_approval_replay_preserves_same_turn_goal_plan_and_approval(tmp_path):
    turn_runtime, continuity, lower = runtime(tmp_path)
    autonomy = WaitingApprovalAutonomy()
    turn_runtime.attach_autonomy(autonomy)
    with pytest.raises(TurnReplayBlocked, match='waiting for canonical owner approval'):
        turn_runtime.chat(MULTISTEP, request_id=RID, device_id='d1', session_id='s1')
    first = turn_runtime.turn(RID)
    assert first['status'] == 'needs_approval'
    assert first['p10_goal_id'] == 'g1' and first['p10_plan_id'] == 'p1' and first['approval_id'] == 'a1'
    with pytest.raises(TurnReplayBlocked, match='needs_approval'):
        turn_runtime.chat(MULTISTEP, request_id=RID, device_id='d1', session_id='s1')
    second = turn_runtime.turn(RID)
    assert second['p10_goal_id'] == 'g1' and second['p10_plan_id'] == 'p1' and second['approval_id'] == 'a1'
    assert len(autonomy.goals) == 1 and len(autonomy.plans) == 1 and autonomy.executed == [('p1', 't1')]
    assert lower.calls == 0
    thread = continuity.active_for_device('d1')
    assert [event['kind'] for event in continuity.events_for_thread(thread['id'])] == ['user_message']


def test_completed_transport_replay_does_not_duplicate_activity_projection(tmp_path):
    audit = AuditStore()
    lower = Executor(audit=audit)
    turn_runtime, _, _ = runtime(tmp_path, lower)
    first = turn_runtime.chat('activity', request_id=RID, device_id='d1')
    second = turn_runtime.chat('activity', request_id=RID, device_id='d1')
    assert first == second == 'answer:activity'
    assert lower.calls == 1
    activities = ActivitiesProjection(audit).list(limit=20)
    assert len(activities) == 1
    assert activities[0]['status'] == 'completed'


def test_stage8_device_revocation_cooperatively_stops_only_bound_turn(tmp_path):
    started = threading.Event()
    stopped = threading.Event()

    class BlockingExecutor(Executor):
        def chat(self, text, **kwargs):
            event = kwargs['cancel_event']
            started.set()
            deadline = time.time() + 2
            while not event.is_set() and time.time() < deadline:
                time.sleep(0.005)
            if event.is_set():
                stopped.set()
                raise ExecutionCancelled('device revoked')
            return 'unexpected completion'

    turn_runtime, _, _ = runtime(tmp_path, BlockingExecutor())
    error = []

    def run_turn():
        try:
            turn_runtime.chat(
                'long task',
                request_id=RID,
                device_id='device-a',
                session_id='session-a',
            )
        except ExecutionCancelled:
            error.append('cancelled')

    worker = threading.Thread(target=run_turn)
    worker.start()
    assert started.wait(1)
    assert turn_runtime.cancel_device_turns('device-b') == 0
    assert stopped.is_set() is False
    assert turn_runtime.cancel_device_turns('device-a') == 1
    worker.join(2)

    assert error == ['cancelled']
    assert stopped.is_set() is True
    assert turn_runtime.turn(RID)['status'] == 'cancelled'
