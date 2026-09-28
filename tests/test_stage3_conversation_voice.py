from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agent.executor import ConfirmationRequired
from core.events import EventBus
from core.personal_ai_runtime import CanonicalTurnRuntime
from core.runtime_state import RuntimeState
from devices.continuity import ContinuityService
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.approval_api import approval_router
from server.conversation_voice_api import (
    CanonicalVoiceTurnBody,
    VoiceBargeBody,
    VoiceClientEventBody,
    conversation_voice_router,
)
from server.logical_request_middleware import _logical_request_id
from server.session_bound_executor import SessionBoundExecutor


R1 = '11111111-1111-4111-8111-111111111111'
R2 = '22222222-2222-4222-8222-222222222222'


class _Registry:
    def is_active(self, device_id):
        return device_id == 'd1'

    def authorize(self, device_id, scope):
        return device_id == 'd1' and scope == 'ai:chat'


class _InnerExecutor:
    def __init__(self, *, approval=False):
        self.calls = []
        self.approval = approval
        self.approve_calls = 0

    def chat(self, text, **kwargs):
        self.calls.append((text, dict(kwargs)))
        if self.approval:
            raise ConfirmationRequired(
                'send_message',
                {'recipient': 'owner@example.com', 'body': text},
                'Send the governed message',
                approval_id='a1',
                execution_id='e1',
                expires_at=9999999999,
            )
        return f'reply:{text}'

    def approve(self, approval_id, **kwargs):
        self.approve_calls += 1
        assert approval_id == 'a1'
        return 'sent'

    def reject(self, approval_id, **kwargs):
        return 'Action cancelled.'


class _ApprovalAgent:
    def approval_result(self, approval_id):
        if approval_id != 'a1':
            return None
        return {
            'approval_id': 'a1',
            'status': 'pending',
            'device_id': 'd1',
            'session_id': 's1',
            'outcome': None,
        }

    def pending_approvals_safe(self, **kwargs):
        return []


class _CancelProbe:
    def __init__(self):
        self.cancelled = []

    def cancel_turn(self, request_id):
        self.cancelled.append(request_id)
        return {'request_id': request_id, 'status': 'cancelled'}


def _request(modality='voice'):
    return Request({
        'type': 'http',
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'https',
        'path': '/iphone/api/voice/turn',
        'raw_path': b'/iphone/api/voice/turn',
        'query_string': b'',
        'headers': [(b'x-personal-ai-input-modality', modality.encode())],
        'client': ('test', 123),
        'server': ('test', 443),
    })


def _endpoint(router, path, method):
    return next(route.endpoint for route in router.routes if route.path == path and method in route.methods)


def _stack(tmp_path, *, approval=False):
    events = EventBus()
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3', events=events)
    inner = _InnerExecutor(approval=approval)
    canonical = CanonicalTurnRuntime(inner, continuity, tmp_path / 'turns.sqlite3', events=events)
    executor = SessionBoundExecutor(canonical, continuity=continuity, surface='iphone-pwa')
    runtime = {
        'device_registry': _Registry(),
        'continuity': continuity,
        'events': events,
        'runtime_state': events.runtime_state,
    }
    router = conversation_voice_router(runtime, executor)
    return events, continuity, inner, canonical, executor, router


def _call_voice(endpoint, body, *, request_id):
    trusted = set_trusted_request(TrustedRequestContext(device_id='d1', session_id='s1'))
    logical = _logical_request_id.set(request_id)
    try:
        return asyncio.run(endpoint(body, _request('voice')))
    finally:
        _logical_request_id.reset(logical)
        reset_trusted_request(trusted)


def test_voice_retry_replays_one_canonical_turn_without_duplicate_conversation_events(tmp_path):
    _, continuity, inner, canonical, _, router = _stack(tmp_path)
    endpoint = _endpoint(router, '/iphone/api/voice/turn', 'POST')
    body = CanonicalVoiceTurnBody(request_id=R1, transcript='hello')

    first = _call_voice(endpoint, body, request_id=R1)
    second = _call_voice(endpoint, body, request_id=R1)

    assert first['request_id'] == R1 == second['request_id']
    assert first['reply'] == 'reply:hello' == second['reply']
    assert len(inner.calls) == 1
    turn = canonical.turn(R1)
    assert turn['status'] == 'completed'
    assert turn['input_modality'] == 'voice'
    assert turn['device_id'] == 'd1'
    assert turn['session_id'] == 's1'
    events = continuity.events_for_thread(turn['conversation_id'])
    assert [event['event_id'] for event in events] == [f'{R1}:user', f'{R1}:assistant']


def test_voice_transport_rejects_logical_request_mismatch_before_execution(tmp_path):
    _, _, inner, _, _, router = _stack(tmp_path)
    endpoint = _endpoint(router, '/iphone/api/voice/turn', 'POST')
    body = CanonicalVoiceTurnBody(request_id=R1, transcript='hello')
    trusted = set_trusted_request(TrustedRequestContext(device_id='d1', session_id='s1'))
    logical = _logical_request_id.set(R2)
    try:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(endpoint(body, _request('voice')))
    finally:
        _logical_request_id.reset(logical)
        reset_trusted_request(trusted)
    assert caught.value.status_code == 409
    assert inner.calls == []


def test_stale_r1_tts_event_cannot_move_active_r2_runtime_state(tmp_path):
    events, _, _, _, _, router = _stack(tmp_path)
    endpoint = _endpoint(router, '/iphone/api/voice/client-event', 'POST')
    stale_events = []
    events.subscribe('voice.output.stale_ignored', stale_events.append)
    events.emit('turn.started', request_id=R2)
    before = events.runtime_state.snapshot()
    assert before.request_id == R2
    assert before.state == RuntimeState.UNDERSTANDING

    trusted = set_trusted_request(TrustedRequestContext(device_id='d1', session_id='s1'))
    try:
        result = endpoint(VoiceClientEventBody(event='tts_started', request_id=R1))
    finally:
        reset_trusted_request(trusted)

    after = events.runtime_state.snapshot()
    assert result == {'ok': True, 'stale': True}
    assert after.request_id == R2
    assert after.state == RuntimeState.UNDERSTANDING
    assert stale_events[-1]['request_id'] == R1


def test_barge_in_interrupts_playback_without_cancelling_canonical_operation(tmp_path):
    events = EventBus()
    probe = _CancelProbe()
    router = conversation_voice_router(
        {'device_registry': _Registry(), 'events': events, 'runtime_state': events.runtime_state},
        probe,
    )
    endpoint = _endpoint(router, '/iphone/api/voice/barge', 'POST')
    trusted = set_trusted_request(TrustedRequestContext(device_id='d1', session_id='s1'))
    try:
        result = endpoint(VoiceBargeBody(speaking=True, request_id=R1))
    finally:
        reset_trusted_request(trusted)
    assert result['playback_interrupted'] is True
    assert result['cancelled_server_turn'] is False
    assert probe.cancelled == []


def test_conversation_history_cursor_is_bounded_and_non_overlapping(tmp_path):
    _, continuity, _, _, _, router = _stack(tmp_path)
    thread_id = continuity.create_thread('History', device_id='d1')
    for index in range(5):
        continuity.append(
            thread_id,
            device_id='d1',
            kind='user_message' if index % 2 == 0 else 'assistant_message',
            payload={'text': f'm{index}'},
            event_id=f'e{index}',
        )
    endpoint = _endpoint(router, '/iphone/api/conversations/{conversation_id}', 'GET')
    trusted = set_trusted_request(TrustedRequestContext(device_id='d1', session_id='s1'))
    try:
        first = endpoint(thread_id, after_sequence=0, limit=2)
        second = endpoint(thread_id, after_sequence=first['next_after_sequence'], limit=2)
    finally:
        reset_trusted_request(trusted)
    first_ids = [row['event_id'] for row in first['events']]
    second_ids = [row['event_id'] for row in second['events']]
    assert first_ids == ['e0', 'e1']
    assert second_ids == ['e2', 'e3']
    assert set(first_ids).isdisjoint(second_ids)
    assert first['limit'] == 2 == second['limit']


def test_voice_approval_resumes_and_completes_the_original_canonical_request(tmp_path):
    _, continuity, inner, canonical, executor, voice_router = _stack(tmp_path, approval=True)
    voice_endpoint = _endpoint(voice_router, '/iphone/api/voice/turn', 'POST')
    body = CanonicalVoiceTurnBody(request_id=R1, transcript='send it')
    pending = _call_voice(voice_endpoint, body, request_id=R1)
    assert pending.status_code == 202
    assert canonical.turn(R1)['status'] == 'needs_approval'
    assert canonical.turn(R1)['approval_id'] == 'a1'

    approvals = approval_router(
        {'device_registry': _Registry(), 'agent_executor': _ApprovalAgent(), 'turn_runtime': canonical},
        executor,
    )
    approve_endpoint = _endpoint(approvals, '/iphone/api/approval/{approval_id}/approve', 'POST')
    trusted = set_trusted_request(TrustedRequestContext(device_id='d1', session_id='s1'))
    try:
        completed = approve_endpoint('a1')
    finally:
        reset_trusted_request(trusted)

    assert completed['request_id'] == R1
    assert completed['reply'] == 'sent'
    assert canonical.turn(R1)['status'] == 'completed'
    assert inner.approve_calls == 1
    thread_events = continuity.events_for_thread(canonical.turn(R1)['conversation_id'])
    assert [event['event_id'] for event in thread_events] == [f'{R1}:user', f'{R1}:assistant']
