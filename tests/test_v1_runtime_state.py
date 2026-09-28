from __future__ import annotations

import pytest

from core.events import EventBus
from core.runtime_state import RuntimeState, normalize_runtime_state


def authority():
    return EventBus().runtime_state


def test_legacy_names_normalize_to_canonical_contract():
    assert normalize_runtime_state('memory') is RuntimeState.MEMORY_RETRIEVAL
    assert normalize_runtime_state('knowledge') is RuntimeState.KNOWLEDGE_RETRIEVAL
    assert normalize_runtime_state('acting') is RuntimeState.TOOL_ACTION
    assert normalize_runtime_state('speaking') is RuntimeState.RESPONDING
    assert normalize_runtime_state('approval') is RuntimeState.NEEDS_APPROVAL
    assert normalize_runtime_state('warning') is RuntimeState.WARNING


def test_required_conversation_state_paths_are_legal():
    state = authority()
    path = [
        RuntimeState.ACTIVE, RuntimeState.LISTENING, RuntimeState.UNDERSTANDING,
        RuntimeState.MEMORY_RETRIEVAL, RuntimeState.KNOWLEDGE_RETRIEVAL,
        RuntimeState.THINKING, RuntimeState.NEEDS_APPROVAL, RuntimeState.TOOL_ACTION,
        RuntimeState.SUCCESS, RuntimeState.RESPONDING, RuntimeState.IDLE,
    ]
    for target in path:
        state.transition(target, reason='test')
    assert state.state is RuntimeState.IDLE


def test_understanding_can_go_directly_to_memory_knowledge_or_thinking():
    for target in (RuntimeState.MEMORY_RETRIEVAL, RuntimeState.KNOWLEDGE_RETRIEVAL, RuntimeState.THINKING):
        state = authority()
        state.transition(RuntimeState.ACTIVE, reason='activate')
        state.transition(RuntimeState.UNDERSTANDING, reason='input')
        state.transition(target, reason='work')
        assert state.state is target


def test_tool_warning_can_recover_or_respond():
    state = authority()
    state.transition(RuntimeState.ACTIVE, reason='activate')
    state.transition(RuntimeState.UNDERSTANDING, reason='input')
    state.transition(RuntimeState.THINKING, reason='plan')
    state.transition(RuntimeState.TOOL_ACTION, reason='dispatch')
    state.transition(RuntimeState.WARNING, reason='verification')
    state.transition(RuntimeState.TOOL_ACTION, reason='recovery')
    state.transition(RuntimeState.SUCCESS, reason='verified')
    assert state.state is RuntimeState.SUCCESS


def test_background_can_return_to_active():
    state = authority()
    state.transition(RuntimeState.BACKGROUND, reason='background')
    state.transition(RuntimeState.ACTIVE, reason='owner_foreground')
    assert state.state is RuntimeState.ACTIVE


def test_error_recovers_only_to_safe_entry_states():
    state = authority()
    state.transition(RuntimeState.ERROR, reason='failure')
    state.transition(RuntimeState.IDLE, reason='safe_reset')
    assert state.state is RuntimeState.IDLE


def test_illegal_transition_fails_closed():
    state = authority()
    with pytest.raises(ValueError):
        state.transition(RuntimeState.TOOL_ACTION, reason='ui_cannot_invent_action')
    assert state.state is RuntimeState.IDLE


def test_legacy_event_boundary_emits_canonical_runtime_state():
    events = EventBus()
    seen = []
    events.subscribe('runtime.state', seen.append)
    events.emit('state', state='active')
    events.emit('state', state='listening')
    events.emit('state', state='understanding')
    events.emit('state', state='memory')
    assert seen[-1]['state'] == RuntimeState.MEMORY_RETRIEVAL.value
    assert seen[-1]['previous_state'] == RuntimeState.UNDERSTANDING.value


def test_cancellation_and_failure_are_runtime_driven():
    events = EventBus()
    state = events.runtime_state
    events.emit('state', state='active')
    events.emit('turn.started', request_id='r1')
    events.emit('turn.failed', request_id='r1')
    assert state.state is RuntimeState.ERROR
    state.transition(RuntimeState.IDLE, reason='safe_reset')
    events.emit('state', state='active')
    events.emit('turn.started', request_id='r2')
    events.emit('turn.cancelled', request_id='r2')
    assert state.state is RuntimeState.IDLE


def test_emergency_stop_can_force_terminal_error_projection():
    state = authority()
    state.transition(RuntimeState.ACTIVE, reason='active')
    state.transition(RuntimeState.ERROR, reason='emergency_stop')
    assert state.state is RuntimeState.ERROR



def test_unscoped_voice_lifecycle_cannot_steal_busy_foreground_request():
    events = EventBus()
    state = events.runtime_state
    ignored = []
    events.subscribe('runtime.state.unscoped_voice_ignored', ignored.append)

    events.emit('turn.started', request_id='typed-r1')
    assert state.state is RuntimeState.UNDERSTANDING
    assert state.snapshot().request_id == 'typed-r1'

    events.emit('voice.listening.started', source='desktop-voice')
    events.emit('voice.stt.failed', source='desktop-voice', error_type='RuntimeError')
    events.emit('voice.session.stopped', source='desktop-voice')

    assert state.state is RuntimeState.UNDERSTANDING
    assert state.snapshot().request_id == 'typed-r1'
    assert len(ignored) == 3


def test_unscoped_voice_lifecycle_cannot_take_over_background_work():
    events = EventBus()
    state = events.runtime_state
    state.transition(RuntimeState.BACKGROUND, reason='background')
    events.emit('voice.listening.started', source='desktop-voice')
    events.emit('voice.session.stopped', source='desktop-voice')
    assert state.state is RuntimeState.BACKGROUND


def test_voice_can_listen_after_terminal_foreground_request():
    events = EventBus()
    state = events.runtime_state
    events.emit('turn.started', request_id='voice-r1')
    events.emit('turn.completed', request_id='voice-r1')
    assert state.state is RuntimeState.SUCCESS

    events.emit('voice.listening.started', source='desktop-voice')

    assert state.state is RuntimeState.LISTENING


def test_request_scoped_voice_stop_can_close_its_own_foreground_lifecycle():
    events = EventBus()
    state = events.runtime_state
    events.emit('turn.started', request_id='voice-r1')
    events.emit('voice.session.stopped', request_id='voice-r1', source='desktop-voice')
    assert state.state is RuntimeState.IDLE
    assert state.snapshot().request_id == 'voice-r1'
