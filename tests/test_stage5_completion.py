from pathlib import Path
import pytest
from core.events import EventBus
from core.runtime_presentation import PRESENTATIONS, presentation_for
from core.runtime_state import RuntimeState
from desktop.floating_presence import PresenceController

@pytest.mark.parametrize('state', list(RuntimeState))
def test_all_states_have_explicit_presentation(state):
    p=presentation_for(state); assert p and p.state is state and p.label and p.visual

def test_presentation_vocabulary_exact(): assert set(PRESENTATIONS)==set(RuntimeState)
def test_unknown_state_safe(): assert presentation_for('FUTURE_STATE') is None
def test_empty_state_safe(): assert presentation_for('') is None
def test_success_distinct(): assert presentation_for('SUCCESS').visual=='success'
def test_warning_distinct(): assert presentation_for('WARNING').visual=='warning'
def test_error_distinct(): assert presentation_for('ERROR').visual=='error'
def test_approval_accessible(): assert presentation_for('NEEDS_APPROVAL').label=='Needs approval'
def test_memory_knowledge_distinct(): assert presentation_for('MEMORY_RETRIEVAL').visual!=presentation_for('KNOWLEDGE_RETRIEVAL').visual
def test_tool_not_success(): assert presentation_for('TOOL_ACTION').visual!='success'
def test_background_not_thinking(): assert presentation_for('BACKGROUND').visual!=presentation_for('THINKING').visual

def test_presence_snapshot_reconstruction(tmp_path):
    e=EventBus(); e.runtime_state.transition(RuntimeState.ACTIVE,reason='owner'); c=PresenceController(e,tmp_path/'p.json')
    try: assert (c.state,c.sequence)==(RuntimeState.ACTIVE,e.runtime_state.snapshot().sequence)
    finally:c.close()

def test_presence_tracks_sequence(tmp_path):
    e=EventBus(); c=PresenceController(e,tmp_path/'p.json')
    try:
        e.runtime_state.transition(RuntimeState.ACTIVE,reason='owner'); assert c.sequence==e.runtime_state.snapshot().sequence
    finally:c.close()

def test_presence_duplicate_rejected(tmp_path):
    e=EventBus(); c=PresenceController(e,tmp_path/'p.json'); before=(c.state,c.sequence); c._on_runtime_state({'state':'ERROR','sequence':c.sequence}); assert (c.state,c.sequence)==before; c.close()
def test_presence_stale_rejected(tmp_path):
    e=EventBus(); c=PresenceController(e,tmp_path/'p.json'); before=(c.state,c.sequence); c._on_runtime_state({'state':'ERROR','sequence':c.sequence-1}); assert (c.state,c.sequence)==before; c.close()
def test_presence_unknown_preserves_truth(tmp_path):
    e=EventBus(); c=PresenceController(e,tmp_path/'p.json'); before=(c.state,c.sequence); c._on_runtime_state({'state':'FUTURE','sequence':c.sequence+1}); assert (c.state,c.sequence)==before; c.close()
def test_presence_missing_sequence_safe(tmp_path):
    e=EventBus(); c=PresenceController(e,tmp_path/'p.json'); before=(c.state,c.sequence); c._on_runtime_state({'state':'ERROR'}); assert (c.state,c.sequence)==before; c.close()
def test_presence_cleanup(tmp_path):
    e=EventBus(); c=PresenceController(e,tmp_path/'p.json'); c.close(); before=(c.state,c.sequence); e.runtime_state.transition(RuntimeState.ACTIVE,reason='owner'); assert (c.state,c.sequence)==before

def test_presence_no_second_authority():
    s=Path('desktop/floating_presence.py').read_text(); assert 'RuntimeStateAuthority(' not in s and "subscribe('runtime.state'" in s and 'runtime_state.snapshot()' in s

def test_desktop_launches_canonical_home():
    s=Path('app/main.py').read_text(); assert 'from ui.canonical_main_window import CanonicalMainWindow' in s and 'window=CanonicalMainWindow(' in s

def test_canonical_home_ignores_legacy_state_events():
    s=Path('ui/canonical_main_window.py').read_text(); assert "subscribe('runtime.state'" in s and 'Legacy `state` events are explicitly non-authoritative' in s

def test_canonical_home_sequence_guard():
    s=Path('ui/canonical_main_window.py').read_text(); assert 'sequence <= self._canonical_sequence' in s

def test_canonical_home_unknown_safe():
    s=Path('ui/canonical_main_window.py').read_text(); assert 'presentation is None or sequence <= self._canonical_sequence' in s

def test_pulse_terminal_visuals():
    s=Path('ui/pulse.py').read_text(); assert all(x in s for x in ('"success"','"warning"','"error"'))
def test_pulse_reduced_motion():
    s=Path('ui/pulse.py').read_text(); assert 'set_reduce_motion' in s and '120 if self.reduce_motion else 16' in s
def test_pulse_unknown_not_success():
    s=Path('ui/pulse.py').read_text(); assert 'else "warning"' in s

def test_pwa_inflight_guard():
    s=Path('pwa/v1-runtime.js').read_text(); assert 'stateRefreshInFlight' in s
def test_pwa_hidden_tab_pause():
    s=Path('pwa/v1-runtime.js').read_text(); assert "document.visibilityState==='hidden'" in s
def test_pwa_bounded_backoff():
    s=Path('pwa/v1-runtime.js').read_text(); assert 'STATE_BACKOFF_MAX_MS=12000' in s and 'Math.min(STATE_BACKOFF_MAX_MS' in s
def test_pwa_pagehide_cleanup():
    s=Path('pwa/v1-runtime.js').read_text(); assert "addEventListener('pagehide'" in s and 'clearTimeout(statePollTimer)' in s
def test_pwa_visibility_resync():
    s=Path('pwa/v1-runtime.js').read_text(); assert "addEventListener('visibilitychange'" in s and 'refreshCanonicalState' in s
def test_pwa_unknown_rejected():
    s=Path('pwa/v1-runtime.js').read_text(); assert '!CANONICAL_STATES.has(canonicalName)' in s
def test_pwa_stale_rejected():
    s=Path('pwa/v1-runtime.js').read_text(); assert 'sequence<=canonicalSequence' in s
def test_state_payload_redacted():
    s=Path('server/runtime_state_api.py').read_text(); assert 'project_home_state(authority.snapshot()).as_dict()' in s and "'reason'" not in s
def test_presentation_has_no_authority():
    s=Path('core/runtime_presentation.py').read_text().lower(); assert 'runtimestateauthority(' not in s and 'executor' not in s
