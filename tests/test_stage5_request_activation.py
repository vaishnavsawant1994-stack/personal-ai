import pytest

from core.events import EventBus
from core.runtime_state import RuntimeState


def test_turn_started_from_idle_uses_legal_atomic_activation_route():
    events = EventBus()
    observed = []
    events.subscribe('runtime.state', observed.append)

    events.emit('turn.started', request_id='r2')

    snapshot = events.runtime_state.snapshot()
    assert snapshot.request_id == 'r2'
    assert snapshot.state == RuntimeState.UNDERSTANDING
    assert [(item['previous_state'], item['state']) for item in observed] == [
        ('IDLE', 'ACTIVE'),
        ('ACTIVE', 'UNDERSTANDING'),
    ]
    assert [item['sequence'] for item in observed] == [1, 2]
    assert all(item['request_id'] == 'r2' for item in observed)


def test_illegal_direct_activation_rolls_back_request_ownership():
    events = EventBus()
    runtime = events.runtime_state
    before = runtime.snapshot()

    with pytest.raises(ValueError):
        runtime.transition(
            RuntimeState.UNDERSTANDING,
            reason='illegal-shortcut',
            request_id='r2',
            activate_request=True,
        )

    after = runtime.snapshot()
    assert after.state == before.state == RuntimeState.IDLE
    assert after.sequence == before.sequence == 0
    assert after.request_id is None


def test_duplicate_turn_started_for_same_request_is_idempotent():
    events = EventBus()
    events.emit('turn.started', request_id='r2')
    before = events.runtime_state.snapshot()
    events.emit('turn.started', request_id='r2')
    assert events.runtime_state.snapshot() == before


@pytest.mark.parametrize('late_state', list(RuntimeState))
def test_every_stale_r1_semantic_state_is_rejected_after_r2_takeover(late_state):
    events = EventBus()
    runtime = events.runtime_state
    events.emit('turn.started', request_id='r1')
    runtime.transition(RuntimeState.THINKING, reason='r1-thinking', request_id='r1')
    events.emit('turn.started', request_id='r2')
    before = runtime.snapshot()

    late = runtime.transition(late_state, reason='late-r1', request_id='r1')

    assert late.sequence == before.sequence
    assert late.request_id == 'r2'
    assert runtime.snapshot() == before


def test_stale_r1_terminal_events_cannot_replace_r2_foreground():
    events = EventBus()
    runtime = events.runtime_state
    events.emit('turn.started', request_id='r1')
    runtime.transition(RuntimeState.RESPONDING, reason='r1-responding', request_id='r1')
    events.emit('turn.started', request_id='r2')
    before = runtime.snapshot()

    events.emit('turn.completed', request_id='r1')
    events.emit('turn.failed', request_id='r1')
    events.emit('voice.tts.started', request_id='r1')
    events.emit('voice.tts.completed', request_id='r1')

    assert runtime.snapshot() == before
    assert before.state == RuntimeState.UNDERSTANDING
    assert before.request_id == 'r2'


def test_background_request_can_continue_without_foreground_authority():
    events = EventBus()
    runtime = events.runtime_state
    runtime.transition(RuntimeState.BACKGROUND, reason='background-r1', request_id='r1')
    events.emit('turn.started', request_id='r2')
    foreground = runtime.snapshot()

    late_background_result = runtime.transition(RuntimeState.THINKING, reason='r1-progress', request_id='r1')

    assert late_background_result.sequence == foreground.sequence
    assert runtime.snapshot() == foreground
    assert foreground.state == RuntimeState.UNDERSTANDING
    assert foreground.request_id == 'r2'
