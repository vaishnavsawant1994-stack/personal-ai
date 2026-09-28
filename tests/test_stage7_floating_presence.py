from pathlib import Path

from core.events import EventBus
from core.runtime_state import RuntimeState
from desktop.floating_presence import PresenceController


def test_presence_controller_reconstructs_canonical_snapshot_and_ignores_stale_events(tmp_path):
    events = EventBus()
    events.runtime_state.transition(RuntimeState.ACTIVE, reason='ready')
    controller = PresenceController(events, tmp_path / 'presence.json')
    assert controller.state == RuntimeState.ACTIVE
    assert controller.sequence == events.runtime_state.snapshot().sequence

    events.runtime_state.transition(RuntimeState.LISTENING, reason='voice')
    assert controller.state == RuntimeState.LISTENING
    sequence = controller.sequence
    events.emit('runtime.state', state='ERROR', sequence=sequence)
    assert controller.state == RuntimeState.LISTENING
    assert controller.sequence == sequence
    controller.close()


def test_presence_controller_follows_all_canonical_runtime_states(tmp_path):
    events = EventBus()
    controller = PresenceController(events, tmp_path / 'presence.json')
    sequence = controller.sequence
    states = [
        RuntimeState.ACTIVE, RuntimeState.LISTENING, RuntimeState.UNDERSTANDING,
        RuntimeState.THINKING, RuntimeState.MEMORY_RETRIEVAL,
        RuntimeState.KNOWLEDGE_RETRIEVAL, RuntimeState.TOOL_ACTION,
        RuntimeState.RESPONDING, RuntimeState.NEEDS_APPROVAL,
        RuntimeState.BACKGROUND, RuntimeState.SUCCESS, RuntimeState.WARNING,
        RuntimeState.ERROR, RuntimeState.IDLE,
    ]
    for state in states:
        sequence += 1
        events.emit('runtime.state', state=state.value, sequence=sequence)
        assert controller.state == state
        assert controller.sequence == sequence
    controller.close()


def test_presence_controller_ignores_unknown_duplicate_and_malformed_events(tmp_path):
    events = EventBus()
    controller = PresenceController(events, tmp_path / 'presence.json')
    initial = controller.state
    sequence = controller.sequence
    events.emit('runtime.state', state='NOT_A_STATE', sequence=sequence + 1)
    events.emit('runtime.state', state='ERROR', sequence='bad')
    events.emit('runtime.state', state='ERROR', sequence=sequence)
    assert controller.state == initial
    assert controller.sequence == sequence
    controller.close()


def test_presence_position_persistence_is_bounded_on_restore(tmp_path):
    path = tmp_path / 'presence.json'
    events = EventBus()
    controller = PresenceController(events, path)
    controller.save_position(9000, -500)
    controller.close()

    restored = PresenceController(events, path)
    assert restored.position == (9000, -500)
    assert restored.clamp_position(
        *restored.position, left=0, top=0, right=1920, bottom=1080, width=118, height=118,
    ) == (1802, 0)
    restored.close()


def test_presence_clamp_supports_negative_secondary_monitor_coordinates():
    assert PresenceController.clamp_position(
        -2500, 120, left=-1920, top=0, right=0, bottom=1080, width=118, height=118,
    ) == (-1920, 120)
    assert PresenceController.clamp_position(
        -100, 1200, left=-1920, top=0, right=0, bottom=1080, width=118, height=118,
    ) == (-118, 962)


def test_presence_controller_unsubscribes_on_close(tmp_path):
    events = EventBus()
    controller = PresenceController(events, tmp_path / 'presence.json')
    state = controller.state
    sequence = controller.sequence
    controller.close()
    events.emit('runtime.state', state='ERROR', sequence=sequence + 1)
    assert controller.state == state
    assert controller.sequence == sequence


def test_floating_presence_source_uses_canonical_turn_cancellation():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    assert "request_id=request_id" in source
    assert "cancel_event=cancel_event" in source
    assert "self.executor.cancel_turn(request_id, device_id='desktop')" in source
    assert "presence.cancel.requested" not in source


def test_floating_presence_window_policy_is_owner_controllable():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    assert "self._always_on_top = True" in source
    assert "def toggle_always_on_top" in source
    assert "Qt.WindowType.WindowStaysOnTopHint" in source
    assert "self.pin.setText('Unpin' if self._always_on_top else 'Pin')" in source


def test_stage7_conversation_projection_preserves_stable_event_identity():
    source = Path('app/main.py').read_text(encoding='utf-8')
    assert 'def append_continuity(kind,text,device_id=None,conversation_id=None,event_id=None)' in source
    assert "event.get('event_id') or event.get('message_id')" in source
    assert "event_id=str(event_id) if event_id else None" in source


def test_stage7_emergency_stop_has_canonical_active_turn_cancellation():
    source = Path('core/personal_ai_runtime.py').read_text(encoding='utf-8')
    assert "def cancel_active_turns(self, *, reason='emergency_stop')" in source
    assert "status NOT IN ('completed','failed','cancelled')" in source
    assert "self._update(str(row['request_id']), 'cancelled'" in source
    assert "self._emit('turn.cancelled'" in source


def test_stage7_emergency_stop_invalidates_approval_before_turn_cancellation():
    source = Path('cloud_runtime/relay.py').read_text(encoding='utf-8')
    invalidate = source.index("if enabled and hasattr(self.executor, 'invalidate_pending_approvals')")
    cancel = source.index("if enabled and hasattr(self.executor, 'cancel_active_turns')")
    assert invalidate < cancel
    assert "self.executor.invalidate_pending_approvals()" in source
    assert "self.executor.cancel_active_turns(reason='emergency_stop')" in source


def test_stage7_invalidated_approval_cannot_reconstruct_after_emergency_stop():
    source = Path('agent/executor.py').read_text(encoding='utf-8')
    assert 'self._paused.clear()' in source
    assert 'self.approvals.advance_security_epoch()' in source
    assert "durable = self.approvals.context(approval_id)" in source
    assert "if durable is None:" in source


def test_floating_presence_shutdown_cancels_active_work_before_unsubscribe():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    close = source[source.index('    def closeEvent(self, event):'):]
    assert 'cancel_event.set()' in close
    assert "self.executor.cancel_turn(request_id, device_id='desktop')" in close
    assert close.index('cancel_event.set()') < close.index('self._unsubscribe()')
    assert close.index("self.executor.cancel_turn(request_id, device_id='desktop')") < close.index('self._unsubscribe()')


def test_floating_presence_compact_mode_does_not_request_keyboard_focus():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    assert 'self.setFocusPolicy(Qt.FocusPolicy.NoFocus)' in source
    panel = source[source.index('    def toggle_panel(self):'):source.index('    def submit(self):')]
    assert 'self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)' in panel
    assert 'self.input.setFocus(Qt.FocusReason.ShortcutFocusReason)' in panel
    assert panel.rfind('self.setFocusPolicy(Qt.FocusPolicy.NoFocus)') > panel.index('else:')
    assert 'self.core.setFocus(Qt.FocusReason.ShortcutFocusReason)' in panel


def test_floating_presence_reclamps_after_non_drag_screen_move():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    move = source[source.index('    def moveEvent(self, event):'):source.index('    def _clamp_to_screen(self):')]
    assert 'super().moveEvent(event)' in move
    assert 'if self._drag_offset is None and not self._clamping_position:' in move
    assert 'self._clamp_to_screen()' in move


def test_floating_presence_tracks_screen_topology_and_available_geometry_changes():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    assert 'QGuiApplication' in source
    assert 'app.screenAdded.connect(self._on_screen_topology_changed)' in source
    assert 'app.screenRemoved.connect(self._on_screen_topology_changed)' in source
    assert 'handle.screenChanged.connect(self._on_window_screen_changed)' in source
    assert 'screen.availableGeometryChanged.connect(self._on_screen_geometry_changed)' in source
    assert 'screen.geometryChanged.connect(self._on_screen_geometry_changed)' in source
    request = source[source.index('    def _request_lifecycle_reclamp(self):'):source.index('    def _reclamp_after_screen_change(self):')]
    assert 'self._drag_offset is not None' in request
    assert 'self._reclamp_pending' in request
    assert 'QTimer.singleShot(0, self._reclamp_after_screen_change)' in request


def test_floating_presence_screen_lifecycle_cleanup_and_clamp_are_reentrant_safe():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    clamp = source[source.index('    def _clamp_to_screen(self):'):source.index('    def _restore_position(self):')]
    assert 'self._clamping_position' in clamp
    assert "if (x, y) == (self.x(), self.y()):" in clamp
    assert 'finally:' in clamp
    close = source[source.index('    def closeEvent(self, event):'):]
    assert 'self._remove_screen_lifecycle()' in close
    assert close.index('self._remove_screen_lifecycle()') < close.index('self.controller.close()')



def test_floating_presence_compact_core_has_keyboard_equivalent_for_double_click():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    build = source[source.index('    def _build(self):'):source.index('    def _render_snapshot(self):')]
    assert "self.core.setAccessibleDescription('Press Enter or Space to open quick controls')" in build
    assert 'self.core.setFocusPolicy(Qt.FocusPolicy.StrongFocus)' in build
    assert 'self.core.keyPressEvent = self._core_key_press' in build
    keyboard = source[source.index('    def _core_key_press(self, event):'):source.index('    def keyPressEvent(self, event):')]
    assert 'Qt.Key.Key_Return' in keyboard
    assert 'Qt.Key.Key_Enter' in keyboard
    assert 'Qt.Key.Key_Space' in keyboard
    assert 'self.toggle_panel()' in keyboard


def test_floating_presence_escape_collapses_quick_controls_and_collapse_is_named():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    assert "self.collapse.setAccessibleName('Collapse quick controls')" in source
    keyboard = source[source.index('    def keyPressEvent(self, event):'):source.index('    def submit(self):')]
    assert 'self._expanded and event.key() == Qt.Key.Key_Escape' in keyboard
    assert 'self.toggle_panel()' in keyboard


def test_floating_presence_runtime_projection_preserves_keyboard_accessibility_hint():
    source = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    projection = source[source.index('    def _apply_projection(self, state_value, sequence):'):source.index('    def _apply_window_flags(self):')]
    assert "self.core.setAccessibleDescription(f'{presentation.label}. Press Enter or Space to open quick controls')" in projection
    assert 'self.core.setAccessibleDescription(presentation.label)' not in projection


def test_stage7_pulse_reduces_background_animation_wakeups():
    source = Path('ui/pulse.py').read_text(encoding='utf-8')
    setter = source[source.index('    def set_state(self,state):'):source.index('    def set_memory_labels', source.index('    def set_state(self,state):'))]
    assert '100 if self.state=="background" else 16' in setter
    assert 'if self.timer.interval()!=interval:self.timer.setInterval(interval)' in setter
    assert '120 if self.reduce_motion' in setter
