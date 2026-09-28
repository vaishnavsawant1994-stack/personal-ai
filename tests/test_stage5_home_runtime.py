from pathlib import Path

import pytest

from core.events import EventBus
from core.home_state_projection import SAFE_STATE_LABELS, project_home_state
from core.runtime_state import LEGAL_TRANSITIONS, RuntimeState, RuntimeStateAuthority


ALL_STATES = list(RuntimeState)


def authority():
    events = EventBus()
    state = RuntimeStateAuthority(events)
    return events, state


def activate(runtime, request_id):
    """Enter a request through the legal production lifecycle."""
    runtime.transition(RuntimeState.ACTIVE, reason='owner_active')
    return runtime.transition(RuntimeState.UNDERSTANDING, reason='turn_started', request_id=request_id, activate_request=True)


def test_single_runtime_state_authority_is_event_bus_authority():
    events = EventBus()
    assert isinstance(events.runtime_state, RuntimeStateAuthority)
    assert events.runtime_state is events.runtime_state


@pytest.mark.parametrize('state', ALL_STATES)
def test_home_projection_covers_every_canonical_state(state):
    # force=True is permitted only here: this is isolated presentation coverage,
    # not production lifecycle qualification.
    events, runtime = authority()
    snapshot = runtime.transition(state, reason='projection-only', force=True)
    projected = project_home_state(snapshot).as_dict()
    assert projected['state'] == state.value
    assert projected['label'] == SAFE_STATE_LABELS[state]
    assert projected['schema_version'] == 1


def test_home_projection_rejects_noncanonical_state():
    class Unsafe:
        state = 'SUCCESS'
        sequence = 9
        request_id = 'r1'
    with pytest.raises(ValueError):
        project_home_state(Unsafe())


def test_legal_transition_graph_preserves_idle_contract():
    assert RuntimeState.UNDERSTANDING not in LEGAL_TRANSITIONS[RuntimeState.IDLE]
    assert RuntimeState.ACTIVE in LEGAL_TRANSITIONS[RuntimeState.IDLE]
    assert RuntimeState.UNDERSTANDING in LEGAL_TRANSITIONS[RuntimeState.ACTIVE]
    assert RuntimeState.UNDERSTANDING in LEGAL_TRANSITIONS[RuntimeState.THINKING]
    assert RuntimeState.UNDERSTANDING in LEGAL_TRANSITIONS[RuntimeState.MEMORY_RETRIEVAL]
    assert RuntimeState.UNDERSTANDING in LEGAL_TRANSITIONS[RuntimeState.KNOWLEDGE_RETRIEVAL]


def test_sequence_is_monotonic_and_duplicate_is_idempotent():
    _, runtime = authority()
    a = runtime.transition(RuntimeState.ACTIVE, reason='a')
    b = runtime.transition(RuntimeState.ACTIVE, reason='duplicate')
    c = runtime.transition(RuntimeState.IDLE, reason='done')
    assert a.sequence == b.sequence
    assert c.sequence == a.sequence + 1


def test_request_r1_r2_isolation_rejects_late_r1_without_force():
    _, runtime = authority()
    activate(runtime, 'r1')
    runtime.transition(RuntimeState.THINKING, reason='r1-thinking', request_id='r1')
    runtime.transition(RuntimeState.UNDERSTANDING, reason='r2', request_id='r2', activate_request=True)
    before = runtime.snapshot()
    late = runtime.transition(RuntimeState.RESPONDING, reason='late-r1', request_id='r1')
    assert late.sequence == before.sequence
    assert late.request_id == 'r2'
    assert runtime.snapshot().state == RuntimeState.UNDERSTANDING


def test_turn_started_event_legally_transfers_foreground_ownership():
    events, runtime = authority()
    activate(runtime, 'r1')
    runtime.transition(RuntimeState.THINKING, reason='r1-thinking', request_id='r1')
    events.emit('turn.started', request_id='r2')
    assert runtime.snapshot().state == RuntimeState.UNDERSTANDING
    assert runtime.snapshot().request_id == 'r2'


@pytest.mark.parametrize('late_state', [
    RuntimeState.MEMORY_RETRIEVAL,
    RuntimeState.KNOWLEDGE_RETRIEVAL,
    RuntimeState.TOOL_ACTION,
    RuntimeState.RESPONDING,
    RuntimeState.SUCCESS,
    RuntimeState.ERROR,
])
def test_stale_states_from_old_request_cannot_take_foreground(late_state):
    _, runtime = authority()
    activate(runtime, 'r1')
    runtime.transition(RuntimeState.THINKING, reason='r1-thinking', request_id='r1')
    runtime.transition(RuntimeState.UNDERSTANDING, reason='r2', request_id='r2', activate_request=True)
    before = runtime.snapshot()
    late = runtime.transition(late_state, reason='late-r1', request_id='r1')
    assert late.sequence == before.sequence
    assert runtime.snapshot() == before


def test_memory_and_knowledge_late_request_states_are_rejected():
    _, runtime = authority()
    activate(runtime, 'r1')
    runtime.transition(RuntimeState.MEMORY_RETRIEVAL, reason='memory', request_id='r1')
    runtime.transition(RuntimeState.UNDERSTANDING, reason='r2', request_id='r2', activate_request=True)
    before = runtime.snapshot()
    runtime.transition(RuntimeState.MEMORY_RETRIEVAL, reason='late-memory', request_id='r1')
    runtime.transition(RuntimeState.KNOWLEDGE_RETRIEVAL, reason='late-knowledge', request_id='r1')
    assert runtime.snapshot() == before


def test_unknown_future_state_preserves_canonical_truth_and_sequence():
    events, runtime = authority()
    runtime.transition(RuntimeState.ACTIVE, reason='owner')
    before = runtime.snapshot()
    diagnostics = []
    unsubscribe = events.subscribe('runtime.state.unknown_ignored', diagnostics.append)
    try:
        result = runtime.transition('FUTURE_STATE', reason='future')
    finally:
        unsubscribe()
    assert result.state == before.state
    assert result.sequence == before.sequence
    assert runtime.snapshot().state == before.state
    assert runtime.snapshot().sequence == before.sequence
    assert diagnostics and diagnostics[-1]['state'] == 'FUTURE_STATE'


def test_illegal_transition_fails_closed():
    _, runtime = authority()
    with pytest.raises(ValueError):
        runtime.transition(RuntimeState.SUCCESS, reason='invented-success')


def test_estop_is_canonical_event_not_home_authority():
    events, runtime = authority()
    events.emit('emergency_stop', request_id=None)
    assert runtime.snapshot().state == RuntimeState.ERROR


def test_voice_listening_and_responding_are_canonical_events():
    events, runtime = authority()
    events.emit('voice.listening.started', request_id='r1')
    assert runtime.snapshot().state == RuntimeState.LISTENING
    runtime.transition(RuntimeState.UNDERSTANDING, reason='heard', request_id='r1')
    events.emit('voice.tts.started', request_id='r1')
    assert runtime.snapshot().state == RuntimeState.RESPONDING


def test_voice_barge_in_new_request_keeps_new_foreground():
    events, runtime = authority()
    activate(runtime, 'r1')
    runtime.transition(RuntimeState.RESPONDING, reason='r1-speaking', request_id='r1')
    events.emit('voice.listening.started', request_id='r2')
    runtime.transition(RuntimeState.UNDERSTANDING, reason='r2-heard', request_id='r2', activate_request=True)
    before = runtime.snapshot()
    runtime.transition(RuntimeState.RESPONDING, reason='late-r1', request_id='r1')
    assert runtime.snapshot() == before
    assert before.request_id == 'r2'


def test_approval_state_is_canonical_event():
    events, runtime = authority()
    activate(runtime, 'r1')
    runtime.transition(RuntimeState.THINKING, reason='plan', request_id='r1')
    events.emit('approval.required', request_id='r1')
    assert runtime.snapshot().state == RuntimeState.NEEDS_APPROVAL


def test_background_state_is_canonical_event():
    events, runtime = authority()
    events.emit('automation.started', request_id=None)
    assert runtime.snapshot().state == RuntimeState.BACKGROUND


def test_background_work_yields_foreground_to_new_request():
    _, runtime = authority()
    runtime.transition(RuntimeState.BACKGROUND, reason='r1-background', request_id='r1')
    runtime.transition(RuntimeState.UNDERSTANDING, reason='r2', request_id='r2', activate_request=True)
    before = runtime.snapshot()
    runtime.transition(RuntimeState.SUCCESS, reason='late-r1-success', request_id='r1')
    assert runtime.snapshot() == before
    assert before.request_id == 'r2'


def test_home_projection_payload_is_redacted():
    _, runtime = authority()
    projected = project_home_state(runtime.snapshot()).as_dict()
    forbidden = {'reason', 'prompt', 'transcript', 'tool_args', 'memory', 'knowledge', 'credentials', 'token'}
    assert forbidden.isdisjoint(projected)


def test_pwa_semantic_state_is_projection_only_and_reconnect_is_bounded():
    source = Path('pwa/v1-runtime.js').read_text(encoding='utf-8')
    assert 'if(!applyingCanonicalState)return;' in source
    assert "api('/runtime-state')" in source
    assert 'sequence<=canonicalSequence' in source
    assert 'STATE_BACKOFF_MAX_MS' in source
    assert 'statePollFailures' in source
    assert 'stateRefreshInFlight' in source
    assert "document.visibilityState==='hidden'" in source
    assert "removeEventListener('visibilitychange'" in source
    assert 'clearTimeout(statePollTimer)' in source


def test_pwa_reconnect_resync_rejects_stale_and_unknown_snapshots():
    source = Path('pwa/v1-runtime.js').read_text(encoding='utf-8')
    assert 'Number(snapshot.schema_version)!==STATE_SCHEMA_VERSION' in source
    assert 'sequence<=canonicalSequence' in source
    assert '!CANONICAL_STATES.has(canonicalName)' in source
    assert 'applyCanonicalState(snapshot)' in source


def test_home_uses_canonical_turn_and_voice_transport():
    source = Path('pwa/v1-runtime.js').read_text(encoding='utf-8')
    assert "api('/voice/turn'" in source
    assert "api('/voice/client-event'" in source
    assert "api('/voice/barge'" in source


def test_home_has_no_direct_provider_or_privileged_tool_transport():
    source = Path('pwa/v1-runtime.js').read_text(encoding='utf-8').lower()
    assert 'api.openai.com' not in source
    assert 'generativelanguage.googleapis.com' not in source
    assert 'api.anthropic.com' not in source
    assert "api('/tool" not in source
    assert "api('/audit" not in source


def test_home_state_endpoint_is_authenticated_and_redacted():
    source = Path('server/runtime_state_api.py').read_text(encoding='utf-8')
    assert 'current_trusted_request' in source
    assert "registry.authorize(context.device_id, 'ai:chat')" in source
    assert 'project_home_state(authority.snapshot()).as_dict()' in source
    assert "'reason'" not in source
