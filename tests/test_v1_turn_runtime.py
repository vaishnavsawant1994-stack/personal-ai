from __future__ import annotations

import pytest

from agent.executor import ConfirmationRequired
from core.personal_ai_runtime import CanonicalTurnRuntime, TurnReplayBlocked
from core.turn_context import current_turn_context
from desktop.operator_context import current_operator_request
from devices.continuity import ContinuityService
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.session_bound_executor import SessionBoundExecutor


class Approvals:
    @staticmethod
    def current_security_epoch():
        return 9


class Executor:
    def __init__(self):
        self.approvals = Approvals()
        self.calls = []
        self.turns = []
        self.operators = []
        self.approved = []

    def chat(self, text, **kwargs):
        self.calls.append((text, kwargs))
        self.turns.append(current_turn_context())
        self.operators.append(current_operator_request())
        return 'reply:' + text

    def approve(self, approval_id, **kwargs):
        self.approved.append((approval_id, kwargs))
        return 'approved reply'

    def reject(self, approval_id, **kwargs):
        return 'Action cancelled.'


class ApprovalExecutor(Executor):
    def chat(self, text, **kwargs):
        self.calls.append((text, kwargs))
        self.turns.append(current_turn_context())
        raise ConfirmationRequired(
            'dangerous.tool',
            {'value': 1},
            'needs owner confirmation',
            approval_id='approval-1',
            execution_id='execution-1',
            expires_at=9999999999.0,
        )


def runtime(tmp_path, raw=None):
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3')
    executor = raw or Executor()
    return (
        CanonicalTurnRuntime(executor, continuity, tmp_path / 'turn-runtime.sqlite3'),
        continuity,
        executor,
    )


def test_canonical_turn_persists_exactly_one_user_and_assistant_projection(tmp_path):
    turn_runtime, continuity, raw = runtime(tmp_path)
    answer = turn_runtime.chat(
        'hello',
        request_id='request-1',
        device_id='device-1',
        session_id='session-1',
        surface='iphone-pwa',
        input_modality='voice',
    )
    assert answer == 'reply:hello'
    thread = continuity.active_for_device('device-1')
    events = continuity.events_for_thread(thread['id'])
    assert [(item['kind'], item['payload']['text']) for item in events] == [
        ('user_message', 'hello'),
        ('assistant_message', 'reply:hello'),
    ]
    turn = turn_runtime.turn('request-1')
    assert turn['status'] == 'completed'
    assert turn['surface'] == 'iphone-pwa'
    assert turn['input_modality'] == 'voice'
    assert len(raw.calls) == 1


def test_completed_request_replay_returns_recorded_answer_without_reexecution(tmp_path):
    turn_runtime, continuity, raw = runtime(tmp_path)
    first = turn_runtime.chat('hello', request_id='request-1', device_id='device-1')
    second = turn_runtime.chat('hello', request_id='request-1', device_id='device-1')
    assert first == second == 'reply:hello'
    assert len(raw.calls) == 1
    thread = continuity.active_for_device('device-1')
    assert len(continuity.events_for_thread(thread['id'])) == 2


def test_request_id_conflict_and_nonterminal_replay_fail_closed(tmp_path):
    turn_runtime, _, _ = runtime(tmp_path)
    turn_runtime.chat('hello', request_id='request-1', device_id='device-1')
    with pytest.raises(PermissionError, match='different turn content'):
        turn_runtime.chat('tampered', request_id='request-1', device_id='device-1')

    approval_runtime, _, _ = runtime(tmp_path / 'approval', ApprovalExecutor())
    with pytest.raises(ConfirmationRequired):
        approval_runtime.chat('do work', request_id='request-2', device_id='device-1')
    assert approval_runtime.turn('request-2')['status'] == 'needs_approval'
    with pytest.raises(TurnReplayBlocked, match='needs_approval'):
        approval_runtime.chat('do work', request_id='request-2', device_id='device-1')


def test_approval_resumes_original_turn_and_projects_single_assistant_result(tmp_path):
    raw = ApprovalExecutor()
    turn_runtime, continuity, _ = runtime(tmp_path, raw)
    with pytest.raises(ConfirmationRequired):
        turn_runtime.chat('do work', request_id='request-1', device_id='device-1', session_id='session-1')
    reply = turn_runtime.approve(
        'approval-1',
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    assert reply == 'approved reply'
    assert turn_runtime.turn('request-1')['status'] == 'completed'
    thread = continuity.active_for_device('device-1')
    events = continuity.events_for_thread(thread['id'])
    assert [item['kind'] for item in events] == ['user_message', 'assistant_message']


def test_authenticated_surface_binds_owner_device_session_and_canonical_context(tmp_path):
    turn_runtime, continuity, raw = runtime(tmp_path)
    bound = SessionBoundExecutor(turn_runtime, continuity=continuity, surface='iphone-pwa')
    token = set_trusted_request(TrustedRequestContext('device-1', 'session-1', 123.0))
    try:
        assert bound.chat('hello', request_id='request-1', input_modality='voice') == 'reply:hello'
    finally:
        reset_trusted_request(token)

    _, kwargs = raw.calls[0]
    assert kwargs['owner_id'] == 'owner'
    assert kwargs['device_id'] == 'device-1'
    assert kwargs['session_id'] == 'session-1'
    turn = raw.turns[0]
    operator = raw.operators[0]
    assert turn.request_id == 'request-1'
    assert turn.device_id == 'device-1'
    assert turn.session_id == 'session-1'
    assert turn.security_epoch == 9
    assert turn.surface == 'iphone-pwa'
    assert turn.input_modality == 'voice'
    assert turn.p8_continuity_refs == (turn.conversation_id,)
    assert operator.owner_id == 'owner'
    assert operator.conversation_id == turn.conversation_id
    assert current_turn_context() is None
    assert current_operator_request() is None


def test_alternate_owner_identity_is_rejected(tmp_path):
    turn_runtime, _, _ = runtime(tmp_path)
    with pytest.raises(PermissionError, match='single-owner'):
        turn_runtime.chat('hello', owner_id='other-owner', request_id='request-1')


def test_continuity_event_id_is_idempotent_and_conflicts_fail_closed(tmp_path):
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3')
    thread = continuity.create_thread('Durable', device_id='device-1')
    first = continuity.append(
        thread,
        device_id='device-1',
        kind='user_message',
        payload={'text': 'hello'},
        event_id='request-1:user',
    )
    retried = continuity.append(
        thread,
        device_id='device-1',
        kind='user_message',
        payload={'text': 'hello'},
        event_id='request-1:user',
    )
    assert first['duplicate'] is False
    assert retried['duplicate'] is True
    assert retried['sequence'] == first['sequence']
    assert len(continuity.events_for_thread(thread)) == 1
    with pytest.raises(ValueError, match='different content'):
        continuity.append(
            thread,
            device_id='device-1',
            kind='user_message',
            payload={'text': 'tampered'},
            event_id='request-1:user',
        )


def test_continuity_history_returns_latest_bounded_turns(tmp_path):
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3')
    thread = continuity.create_thread('History', device_id='device-1')
    for index in range(20):
        continuity.append(
            thread,
            device_id='device-1',
            kind='user_message' if index % 2 == 0 else 'assistant_message',
            payload={'text': f'message-{index}'},
        )
    history = continuity.conversation_history(thread, limit=6)
    assert [item['content'] for item in history] == [f'message-{index}' for index in range(14, 20)]
    assert [item['role'] for item in history] == ['user', 'assistant', 'user', 'assistant', 'user', 'assistant']
