import pytest

from core.events import EventBus
from core.runtime_state import RuntimeState, TERMINAL_REQUEST_STATES


def _r2_thinking(events: EventBus):
    events.emit('turn.started', request_id='r2')
    events.runtime_state.transition(RuntimeState.THINKING, reason='r2-thinking', request_id='r2')
    snapshot = events.runtime_state.snapshot()
    assert snapshot.request_id == 'r2'
    assert snapshot.state is RuntimeState.THINKING
    return snapshot


def _terminal_r1(events: EventBus, terminal: RuntimeState):
    events.emit('turn.started', request_id='r1')
    if terminal is RuntimeState.SUCCESS:
        events.runtime_state.transition(RuntimeState.RESPONDING, reason='reply', request_id='r1')
        events.emit('turn.completed', request_id='r1')
    elif terminal is RuntimeState.WARNING:
        events.runtime_state.transition(RuntimeState.THINKING, reason='thinking', request_id='r1')
        events.emit('tool.unverified', request_id='r1', reason='verification unavailable')
    elif terminal is RuntimeState.ERROR:
        events.emit('turn.failed', request_id='r1')
    else:
        raise AssertionError(f'unsupported terminal: {terminal}')
    snapshot = events.runtime_state.snapshot()
    assert snapshot.state is terminal
    assert snapshot.request_id == 'r1'
    return snapshot


def test_terminal_request_state_set_is_explicit_and_does_not_normalize_transition_graph():
    assert TERMINAL_REQUEST_STATES == frozenset({RuntimeState.SUCCESS, RuntimeState.WARNING, RuntimeState.ERROR})


def test_unscoped_workflow_started_from_idle_projects_background_without_foreground_owner():
    events = EventBus()
    events.emit('workflow.started', run_id='w1')
    snapshot = events.runtime_state.snapshot()
    assert snapshot.state is RuntimeState.BACKGROUND
    assert snapshot.request_id is None


def test_unscoped_background_start_cannot_take_over_active_r2_thinking():
    events = EventBus()
    before = _r2_thinking(events)
    events.emit('workflow.started', run_id='w1')
    assert events.runtime_state.snapshot() == before


@pytest.mark.parametrize('active_state', [
    RuntimeState.ACTIVE,
    RuntimeState.LISTENING,
    RuntimeState.UNDERSTANDING,
    RuntimeState.THINKING,
    RuntimeState.MEMORY_RETRIEVAL,
    RuntimeState.KNOWLEDGE_RETRIEVAL,
    RuntimeState.TOOL_ACTION,
    RuntimeState.RESPONDING,
    RuntimeState.NEEDS_APPROVAL,
])
def test_unscoped_background_cannot_steal_any_active_foreground_state(active_state):
    events = EventBus()
    authority = events.runtime_state
    if active_state is RuntimeState.ACTIVE:
        authority.activate_foreground_request('r2', reason='active-test', target=RuntimeState.ACTIVE)
    elif active_state is RuntimeState.LISTENING:
        authority.activate_foreground_request('r2', reason='listening-test', target=RuntimeState.LISTENING)
    else:
        events.emit('turn.started', request_id='r2')
        if active_state is RuntimeState.UNDERSTANDING:
            pass
        elif active_state is RuntimeState.THINKING:
            authority.transition(RuntimeState.THINKING, reason='thinking', request_id='r2')
        elif active_state is RuntimeState.MEMORY_RETRIEVAL:
            authority.transition(RuntimeState.MEMORY_RETRIEVAL, reason='memory', request_id='r2')
        elif active_state is RuntimeState.KNOWLEDGE_RETRIEVAL:
            authority.transition(RuntimeState.KNOWLEDGE_RETRIEVAL, reason='knowledge', request_id='r2')
        elif active_state is RuntimeState.TOOL_ACTION:
            authority.transition(RuntimeState.THINKING, reason='thinking', request_id='r2')
            authority.transition(RuntimeState.TOOL_ACTION, reason='tool', request_id='r2')
        elif active_state is RuntimeState.RESPONDING:
            authority.transition(RuntimeState.RESPONDING, reason='responding', request_id='r2')
        elif active_state is RuntimeState.NEEDS_APPROVAL:
            authority.transition(RuntimeState.THINKING, reason='thinking', request_id='r2')
            authority.transition(RuntimeState.NEEDS_APPROVAL, reason='approval', request_id='r2')
    before = authority.snapshot()
    assert before.state is active_state
    assert before.request_id == 'r2'
    events.emit('workflow.started', run_id='w1')
    assert authority.snapshot() == before


def test_unscoped_background_agent_states_do_not_escape_background_projection():
    events = EventBus()
    events.emit('workflow.started', run_id='w1')
    before = events.runtime_state.snapshot()
    assert before.state is RuntimeState.BACKGROUND
    assert before.request_id is None

    for state in ('thinking', 'acting', 'speaking', 'success', 'warning', 'error'):
        events.emit('state', state=state)
        assert events.runtime_state.snapshot() == before
    events.emit('tool.unverified', reason='background verification unavailable')
    assert events.runtime_state.snapshot() == before


def test_active_r2_survives_late_unscoped_background_events_after_takeover():
    events = EventBus()
    events.emit('workflow.started', run_id='w1')
    events.emit('turn.started', request_id='r2')
    before = events.runtime_state.snapshot()
    assert before.state is RuntimeState.UNDERSTANDING
    assert before.request_id == 'r2'

    events.emit('workflow.started', run_id='w2')
    events.emit('state', state='thinking')
    events.emit('tool.unverified', reason='background warning')
    assert events.runtime_state.snapshot() == before


def test_scoped_foreground_request_can_intentionally_detach_to_background():
    events = EventBus()
    _r2_thinking(events)
    events.emit('workflow.started', request_id='r2', run_id='w1')
    detached = events.runtime_state.snapshot()
    assert detached.state is RuntimeState.BACKGROUND
    assert detached.request_id == 'r2'

    events.emit('state', state='thinking')
    events.emit('tool.unverified', reason='unscoped background work')
    assert events.runtime_state.snapshot() == detached


@pytest.mark.parametrize('terminal', [RuntimeState.SUCCESS, RuntimeState.WARNING, RuntimeState.ERROR])
def test_terminal_foreground_owner_yields_to_unscoped_background_cannot_resurrect_and_new_r2_wins(terminal):
    events = EventBus()
    _terminal_r1(events, terminal)

    events.emit('workflow.started', run_id='w1')
    background = events.runtime_state.snapshot()
    assert background.state is RuntimeState.BACKGROUND
    assert background.request_id is None

    for late_state in ('thinking', 'speaking', 'success', 'error'):
        events.emit('state', state=late_state, request_id='r1')
        assert events.runtime_state.snapshot() == background
    events.emit('tool.unverified', request_id='r1', reason='late-r1')
    events.emit('workflow.started', request_id='r1', run_id='late-r1')
    events.emit('turn.started', request_id='r1')
    assert events.runtime_state.snapshot() == background

    events.emit('turn.started', request_id='r2')
    foreground = events.runtime_state.snapshot()
    assert foreground.state is RuntimeState.UNDERSTANDING
    assert foreground.request_id == 'r2'

    events.emit('state', state='responding', request_id='r1')
    assert events.runtime_state.snapshot() == foreground


def test_multiple_unscoped_background_workflows_are_bounded_and_deterministic():
    events = EventBus()
    for run_id in ('w1', 'w2', 'w3'):
        events.emit('workflow.started', run_id=run_id)
    background = events.runtime_state.snapshot()
    assert background.state is RuntimeState.BACKGROUND
    assert background.request_id is None
    for state in ('success', 'warning', 'error'):
        events.emit('state', state=state)
        assert events.runtime_state.snapshot() == background


def test_background_terminal_results_cannot_overwrite_active_r2_responding():
    events = EventBus()
    events.emit('workflow.started', run_id='w1')
    events.emit('turn.started', request_id='r2')
    events.runtime_state.transition(RuntimeState.RESPONDING, reason='reply', request_id='r2')
    foreground = events.runtime_state.snapshot()
    for state in ('success', 'warning', 'error'):
        events.emit('state', state=state)
        assert events.runtime_state.snapshot() == foreground


def test_background_to_new_foreground_uses_canonical_atomic_activation_and_late_background_cannot_retakes_it():
    events = EventBus()
    events.emit('workflow.started', run_id='w1')
    assert events.runtime_state.snapshot().state is RuntimeState.BACKGROUND
    events.emit('turn.started', request_id='r2')
    foreground = events.runtime_state.snapshot()
    assert foreground.state is RuntimeState.UNDERSTANDING
    assert foreground.request_id == 'r2'
    events.emit('workflow.started', run_id='w1-late')
    events.emit('state', state='success')
    assert events.runtime_state.snapshot() == foreground


def test_estop_remains_global_during_unscoped_background():
    events = EventBus()
    events.emit('workflow.started', run_id='w1')
    events.emit('emergency_stop')
    snapshot = events.runtime_state.snapshot()
    assert snapshot.state is RuntimeState.ERROR


def test_estop_remains_global_with_active_foreground_and_background_attempts():
    events = EventBus()
    _r2_thinking(events)
    events.emit('workflow.started', run_id='w1')
    events.emit('emergency_stop', request_id='r2')
    snapshot = events.runtime_state.snapshot()
    assert snapshot.state is RuntimeState.ERROR
    assert snapshot.request_id == 'r2'


def test_cancellation_of_scoped_background_request_does_not_resurrect_after_new_foreground():
    events = EventBus()
    _r2_thinking(events)
    events.emit('workflow.started', request_id='r2', run_id='w1')
    assert events.runtime_state.snapshot().state is RuntimeState.BACKGROUND
    events.emit('turn.cancelled', request_id='r2')
    cancelled = events.runtime_state.snapshot()
    assert cancelled.state is RuntimeState.IDLE
    events.emit('turn.started', request_id='r3')
    foreground = events.runtime_state.snapshot()
    events.emit('state', state='thinking', request_id='r2')
    assert events.runtime_state.snapshot() == foreground


def test_foreground_approval_remains_authoritative_while_unscoped_background_exists():
    events = EventBus()
    events.emit('workflow.started', run_id='w1')
    events.emit('turn.started', request_id='r2')
    events.runtime_state.transition(RuntimeState.THINKING, reason='thinking', request_id='r2')
    events.emit('turn.needs_approval', request_id='r2')
    approval = events.runtime_state.snapshot()
    assert approval.state is RuntimeState.NEEDS_APPROVAL
    assert approval.request_id == 'r2'
    events.emit('workflow.started', run_id='w2')
    assert events.runtime_state.snapshot() == approval


def test_unscoped_background_approval_cannot_replace_active_foreground_projection():
    events = EventBus()
    _r2_thinking(events)
    before = events.runtime_state.snapshot()
    events.emit('approval.required')
    assert events.runtime_state.snapshot() == before


def test_stale_r1_scoped_background_start_cannot_move_r2():
    events = EventBus()
    events.emit('turn.started', request_id='r1')
    events.emit('turn.started', request_id='r2')
    events.runtime_state.transition(RuntimeState.THINKING, reason='r2-thinking', request_id='r2')
    before = events.runtime_state.snapshot()

    events.emit('workflow.started', request_id='r1', run_id='late-r1')
    assert events.runtime_state.snapshot() == before
