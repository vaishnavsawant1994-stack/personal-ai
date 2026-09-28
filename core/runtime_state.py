from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock


class RuntimeState(StrEnum):
    IDLE = 'IDLE'
    ACTIVE = 'ACTIVE'
    LISTENING = 'LISTENING'
    UNDERSTANDING = 'UNDERSTANDING'
    THINKING = 'THINKING'
    MEMORY_RETRIEVAL = 'MEMORY_RETRIEVAL'
    KNOWLEDGE_RETRIEVAL = 'KNOWLEDGE_RETRIEVAL'
    TOOL_ACTION = 'TOOL_ACTION'
    RESPONDING = 'RESPONDING'
    NEEDS_APPROVAL = 'NEEDS_APPROVAL'
    BACKGROUND = 'BACKGROUND'
    SUCCESS = 'SUCCESS'
    WARNING = 'WARNING'
    ERROR = 'ERROR'


TERMINAL_REQUEST_STATES = frozenset({
    RuntimeState.SUCCESS,
    RuntimeState.WARNING,
    RuntimeState.ERROR,
})


LEGACY_STATE_ALIASES = {
    'idle': RuntimeState.IDLE,
    'ready': RuntimeState.ACTIVE,
    'active': RuntimeState.ACTIVE,
    'listening': RuntimeState.LISTENING,
    'understanding': RuntimeState.UNDERSTANDING,
    'thinking': RuntimeState.THINKING,
    'memory': RuntimeState.MEMORY_RETRIEVAL,
    'memory_retrieval': RuntimeState.MEMORY_RETRIEVAL,
    'retrieving_memory': RuntimeState.MEMORY_RETRIEVAL,
    'knowledge': RuntimeState.KNOWLEDGE_RETRIEVAL,
    'knowledge_retrieval': RuntimeState.KNOWLEDGE_RETRIEVAL,
    'retrieving_knowledge': RuntimeState.KNOWLEDGE_RETRIEVAL,
    'acting': RuntimeState.TOOL_ACTION,
    'action': RuntimeState.TOOL_ACTION,
    'tool': RuntimeState.TOOL_ACTION,
    'tool_action': RuntimeState.TOOL_ACTION,
    'speaking': RuntimeState.RESPONDING,
    'responding': RuntimeState.RESPONDING,
    'response': RuntimeState.RESPONDING,
    'approval': RuntimeState.NEEDS_APPROVAL,
    'needs_approval': RuntimeState.NEEDS_APPROVAL,
    'waiting_approval': RuntimeState.NEEDS_APPROVAL,
    'background': RuntimeState.BACKGROUND,
    'success': RuntimeState.SUCCESS,
    'warning': RuntimeState.WARNING,
    'error': RuntimeState.ERROR,
}


def _known_runtime_state(value):
    if isinstance(value, RuntimeState):
        return value
    key = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
    if not key:
        return None
    try:
        return RuntimeState[key.upper()]
    except KeyError:
        return LEGACY_STATE_ALIASES.get(key)


def normalize_runtime_state(value):
    """Legacy-compatible normalizer. Canonical authority uses strict recognition."""
    return _known_runtime_state(value) or RuntimeState.IDLE


LEGAL_TRANSITIONS = {
    RuntimeState.IDLE: {RuntimeState.ACTIVE, RuntimeState.LISTENING, RuntimeState.BACKGROUND, RuntimeState.ERROR, RuntimeState.WARNING},
    RuntimeState.ACTIVE: {RuntimeState.IDLE, RuntimeState.LISTENING, RuntimeState.UNDERSTANDING, RuntimeState.BACKGROUND, RuntimeState.ERROR, RuntimeState.WARNING},
    RuntimeState.LISTENING: {RuntimeState.UNDERSTANDING, RuntimeState.ACTIVE, RuntimeState.IDLE, RuntimeState.ERROR, RuntimeState.WARNING},
    RuntimeState.UNDERSTANDING: {RuntimeState.IDLE, RuntimeState.MEMORY_RETRIEVAL, RuntimeState.KNOWLEDGE_RETRIEVAL, RuntimeState.THINKING, RuntimeState.RESPONDING, RuntimeState.ERROR, RuntimeState.WARNING},
    RuntimeState.MEMORY_RETRIEVAL: {RuntimeState.IDLE, RuntimeState.UNDERSTANDING, RuntimeState.KNOWLEDGE_RETRIEVAL, RuntimeState.THINKING, RuntimeState.RESPONDING, RuntimeState.ERROR, RuntimeState.WARNING},
    RuntimeState.KNOWLEDGE_RETRIEVAL: {RuntimeState.IDLE, RuntimeState.UNDERSTANDING, RuntimeState.MEMORY_RETRIEVAL, RuntimeState.THINKING, RuntimeState.RESPONDING, RuntimeState.ERROR, RuntimeState.WARNING},
    RuntimeState.THINKING: {RuntimeState.IDLE, RuntimeState.UNDERSTANDING, RuntimeState.NEEDS_APPROVAL, RuntimeState.TOOL_ACTION, RuntimeState.RESPONDING, RuntimeState.BACKGROUND, RuntimeState.ERROR, RuntimeState.WARNING},
    RuntimeState.NEEDS_APPROVAL: {RuntimeState.UNDERSTANDING, RuntimeState.TOOL_ACTION, RuntimeState.ACTIVE, RuntimeState.IDLE, RuntimeState.ERROR, RuntimeState.WARNING},
    RuntimeState.TOOL_ACTION: {RuntimeState.UNDERSTANDING, RuntimeState.SUCCESS, RuntimeState.WARNING, RuntimeState.RESPONDING, RuntimeState.ERROR},
    RuntimeState.SUCCESS: {RuntimeState.UNDERSTANDING, RuntimeState.RESPONDING, RuntimeState.ACTIVE, RuntimeState.IDLE, RuntimeState.BACKGROUND, RuntimeState.LISTENING},
    RuntimeState.WARNING: {RuntimeState.UNDERSTANDING, RuntimeState.TOOL_ACTION, RuntimeState.RESPONDING, RuntimeState.ACTIVE, RuntimeState.IDLE, RuntimeState.ERROR, RuntimeState.LISTENING},
    RuntimeState.RESPONDING: {RuntimeState.UNDERSTANDING, RuntimeState.IDLE, RuntimeState.ACTIVE, RuntimeState.LISTENING, RuntimeState.ERROR, RuntimeState.WARNING, RuntimeState.SUCCESS},
    RuntimeState.BACKGROUND: {RuntimeState.UNDERSTANDING, RuntimeState.ACTIVE, RuntimeState.IDLE, RuntimeState.THINKING, RuntimeState.ERROR, RuntimeState.WARNING},
    RuntimeState.ERROR: {RuntimeState.UNDERSTANDING, RuntimeState.IDLE, RuntimeState.ACTIVE, RuntimeState.LISTENING},
}


@dataclass(frozen=True)
class StateSnapshot:
    state: RuntimeState
    sequence: int
    reason: str
    request_id: str | None = None


class RuntimeStateAuthority:
    """Canonical V1 user-facing state projection over factual runtime events."""

    MAX_RETIRED_REQUESTS = 128

    def __init__(self, events, *, initial=RuntimeState.IDLE):
        self.events = events
        self._state = initial
        self._sequence = 0
        self._request_id = None
        self._lock = RLock()
        self._subscriptions = []
        self._degraded_requests: set[str] = set()
        self._retired_request_ids: list[str] = []
        self._bind_compatibility_events()

    @property
    def state(self):
        with self._lock:
            return self._state

    def snapshot(self):
        with self._lock:
            return StateSnapshot(self._state, self._sequence, 'current', self._request_id)

    def _retire_request_locked(self, request_id: str | None):
        scoped = str(request_id or '').strip() or None
        if not scoped or scoped in self._retired_request_ids:
            return
        self._retired_request_ids.append(scoped)
        if len(self._retired_request_ids) > self.MAX_RETIRED_REQUESTS:
            del self._retired_request_ids[:-self.MAX_RETIRED_REQUESTS]

    def transition(self, target, *, reason, force=False, request_id=None, activate_request=False, **context):
        normalized = _known_runtime_state(target)
        scoped = str(request_id or '').strip() or None
        stale = False
        if normalized is None:
            snapshot = self.snapshot()
            self.events.emit('runtime.state.unknown_ignored', state=str(target), sequence=snapshot.sequence, request_id=snapshot.request_id)
            return StateSnapshot(snapshot.state, snapshot.sequence, 'unknown_state_ignored', snapshot.request_id)
        with self._lock:
            current = self._state
            previous_request = self._request_id
            retired = bool(scoped and scoped in self._retired_request_ids)
            if scoped and not activate_request and (retired or (self._request_id and scoped != self._request_id)):
                stale = True
                current_request = self._request_id
                snapshot = StateSnapshot(current, self._sequence, 'stale_request_ignored', current_request)
            else:
                changed_request = bool(activate_request and scoped and scoped != previous_request)
                if normalized == current and not changed_request:
                    return StateSnapshot(current, self._sequence, reason, self._request_id)
                if not force and normalized != current and normalized not in LEGAL_TRANSITIONS[current]:
                    raise ValueError(f'illegal runtime state transition: {current.value} -> {normalized.value}')
                if activate_request and scoped:
                    if previous_request and previous_request != scoped:
                        self._retire_request_locked(previous_request)
                    self._request_id = scoped
                elif scoped and self._request_id is None:
                    self._request_id = scoped
                self._sequence += 1
                self._state = normalized
                snapshot = StateSnapshot(normalized, self._sequence, reason, self._request_id)
        if stale:
            self.events.emit('runtime.state.stale_ignored', request_id=scoped, current_request_id=current_request)
            return snapshot
        self.events.emit('runtime.state', state=normalized.value, previous_state=current.value, sequence=snapshot.sequence, reason=str(reason), request_id=snapshot.request_id, **context)
        return snapshot

    def activate_foreground_request(self, request_id, *, reason='turn_started', target=RuntimeState.UNDERSTANDING, **context):
        scoped = str(request_id or '').strip() or None
        normalized = _known_runtime_state(target)
        if not scoped:
            raise ValueError('foreground request activation requires request_id')
        if normalized is None:
            raise ValueError(f'unknown runtime state: {target}')
        with self._lock:
            if scoped in self._retired_request_ids and scoped != self._request_id:
                stale_snapshot = StateSnapshot(self._state, self._sequence, 'stale_request_ignored', self._request_id)
                stale_current_request = self._request_id
            else:
                stale_snapshot = None
                stale_current_request = None
        if stale_snapshot is not None:
            self.events.emit('runtime.state.stale_ignored', request_id=scoped, current_request_id=stale_current_request)
            return stale_snapshot
        records = []
        with self._lock:
            current = self._state
            previous_request = self._request_id
            if scoped == previous_request and normalized == current:
                return StateSnapshot(current, self._sequence, reason, self._request_id)
            if normalized == RuntimeState.UNDERSTANDING and current == RuntimeState.IDLE:
                path = [RuntimeState.ACTIVE, RuntimeState.UNDERSTANDING]
            elif normalized == current:
                path = [normalized]
            elif normalized in LEGAL_TRANSITIONS[current]:
                path = [normalized]
            else:
                raise ValueError(f'illegal runtime state transition: {current.value} -> {normalized.value}')
            probe = current
            for step in path:
                if step != probe and step not in LEGAL_TRANSITIONS[probe]:
                    raise ValueError(f'illegal runtime state transition: {probe.value} -> {step.value}')
                probe = step
            if previous_request and previous_request != scoped:
                self._retire_request_locked(previous_request)
            if scoped != previous_request:
                self._degraded_requests.discard(scoped)
            self._request_id = scoped
            previous = current
            for step in path:
                self._sequence += 1
                self._state = step
                snapshot = StateSnapshot(step, self._sequence, reason, self._request_id)
                records.append((step, previous, snapshot))
                previous = step
            final = StateSnapshot(self._state, self._sequence, reason, self._request_id)
        for step, previous, snapshot in records:
            self.events.emit('runtime.state', state=step.value, previous_state=previous.value, sequence=snapshot.sequence, reason=str(reason), request_id=snapshot.request_id, **context)
        return final

    def complete_foreground_request(self, request_id, *, degraded=False, reason='turn_completed'):
        scoped = str(request_id or '').strip() or None
        if not scoped:
            raise ValueError('foreground request completion requires request_id')
        with self._lock:
            current = self._state
            current_request = self._request_id
        if current_request and scoped != current_request:
            return self.transition(RuntimeState.SUCCESS, reason=reason, request_id=scoped)
        if degraded:
            return self.transition(RuntimeState.WARNING, reason='completed_with_unverified_outcome', request_id=scoped)
        if current == RuntimeState.SUCCESS:
            return self.snapshot()
        if current != RuntimeState.RESPONDING:
            self.transition(RuntimeState.RESPONDING, reason='terminal_response_ready', request_id=scoped)
        return self.transition(RuntimeState.SUCCESS, reason=reason, request_id=scoped)

    def _compat(self, event):
        scoped = str(event.get('request_id') or '').strip() or None
        if scoped is None:
            with self._lock:
                current_request = self._request_id
                current_state = self._state
                snapshot = StateSnapshot(current_state, self._sequence, 'unscoped_compat_ignored', current_request)
            if current_request is not None or current_state == RuntimeState.BACKGROUND:
                self.events.emit('runtime.state.unscoped_compat_ignored', attempted_state=str(event.get('state') or ''), current_state=current_state.value, current_request_id=current_request)
                return snapshot
        try:
            return self.transition(event.get('state'), reason=f"legacy:{event.get('event', 'state')}", request_id=scoped)
        except ValueError:
            return self.snapshot()

    def _safe_transition(self, target, reason, event, *, activate_request=False):
        try:
            if activate_request:
                return self.activate_foreground_request(event.get('request_id'), reason=reason, target=target)
            return self.transition(target, reason=reason, request_id=event.get('request_id'))
        except ValueError:
            return self.snapshot()
        finally:
            if reason in {'owner_cancelled', 'turn_failed'}:
                scoped = str(event.get('request_id') or '').strip()
                if scoped:
                    with self._lock:
                        self._degraded_requests.discard(scoped)

    def _on_background_started(self, event):
        """Project legitimate background work without allowing foreground takeover.

        A request-scoped detach follows the existing legal graph. An unscoped
        background start may take the Core only when no active foreground lifecycle
        owns it. Terminal states retain request provenance for history, but their
        foreground lifecycle has ended: yielding to independent background work
        atomically retires the old request and clears active ownership. This is an
        ownership operation, not a normalization of terminal semantic transitions.
        """
        scoped = str(event.get('request_id') or '').strip() or None
        if scoped:
            return self._safe_transition(RuntimeState.BACKGROUND, 'background_started', event)
        with self._lock:
            current = self._state
            current_request = self._request_id
            terminal_provenance = current in TERMINAL_REQUEST_STATES and current_request is not None
            if current == RuntimeState.BACKGROUND and current_request is None:
                return StateSnapshot(current, self._sequence, 'background_started', None)
            eligible_without_active_owner = current in {RuntimeState.IDLE, RuntimeState.ACTIVE} or current in TERMINAL_REQUEST_STATES
            if (current_request is not None and not terminal_provenance) or not eligible_without_active_owner:
                ignored = StateSnapshot(current, self._sequence, 'background_ignored_for_foreground', current_request)
                should_ignore = True
            else:
                should_ignore = False
                if terminal_provenance:
                    self._retire_request_locked(current_request)
                self._request_id = None
                self._sequence += 1
                self._state = RuntimeState.BACKGROUND
                snapshot = StateSnapshot(RuntimeState.BACKGROUND, self._sequence, 'background_started', None)
        if should_ignore:
            self.events.emit('runtime.state.background_ignored', current_state=current.value, current_request_id=current_request)
            return ignored
        self.events.emit('runtime.state', state=RuntimeState.BACKGROUND.value, previous_state=current.value, sequence=snapshot.sequence, reason='background_started', request_id=None)
        return snapshot

    def _on_voice_state(self, target, reason, event):
        scoped = str(event.get('request_id') or '').strip() or None
        if scoped is None:
            with self._lock:
                current = self._state
                current_request = self._request_id
                busy_foreground = current in {
                    RuntimeState.UNDERSTANDING,
                    RuntimeState.THINKING,
                    RuntimeState.MEMORY_RETRIEVAL,
                    RuntimeState.KNOWLEDGE_RETRIEVAL,
                    RuntimeState.TOOL_ACTION,
                    RuntimeState.RESPONDING,
                    RuntimeState.NEEDS_APPROVAL,
                }
                snapshot = StateSnapshot(current, self._sequence, 'unscoped_voice_ignored', current_request)
            if current == RuntimeState.BACKGROUND or (current_request is not None and busy_foreground):
                self.events.emit(
                    'runtime.state.unscoped_voice_ignored',
                    attempted_state=target.value,
                    current_state=current.value,
                    current_request_id=current_request,
                    voice_event=event.get('event'),
                )
                return snapshot
        return self._safe_transition(target, reason, event)

    def _on_approval_required(self, event):
        """Project approval only when it belongs to the foreground lifecycle.

        Durable approval truth remains outside this projection. An unscoped approval
        emitted by unrelated background work must not steal an active foreground Core.
        """
        scoped = str(event.get('request_id') or '').strip() or None
        if scoped is None:
            with self._lock:
                current_request = self._request_id
                current_state = self._state
                snapshot = StateSnapshot(current_state, self._sequence, 'unscoped_approval_ignored', current_request)
            if current_request is not None:
                self.events.emit('runtime.state.unscoped_approval_ignored', current_state=current_state.value, current_request_id=current_request)
                return snapshot
        return self._safe_transition(RuntimeState.NEEDS_APPROVAL, 'approval_required', event)

    def _on_tool_unverified(self, event):
        scoped = str(event.get('request_id') or '').strip() or None
        if scoped is None:
            with self._lock:
                current_request = self._request_id
                current_state = self._state
                snapshot = StateSnapshot(current_state, self._sequence, 'unscoped_tool_unverified_ignored', current_request)
            if current_request is not None or current_state == RuntimeState.BACKGROUND:
                self.events.emit('runtime.state.unscoped_tool_ignored', current_state=current_state.value, current_request_id=current_request)
                return snapshot
        if scoped:
            with self._lock:
                if self._request_id in {None, scoped} and scoped not in self._retired_request_ids:
                    self._degraded_requests.add(scoped)
        return self._safe_transition(RuntimeState.WARNING, 'verification_warning', event)

    def _on_turn_completed(self, event):
        scoped = str(event.get('request_id') or '').strip() or None
        if not scoped:
            return self.snapshot()
        with self._lock:
            degraded = scoped in self._degraded_requests
        try:
            return self.complete_foreground_request(scoped, degraded=degraded)
        except ValueError:
            return self.snapshot()
        finally:
            with self._lock:
                self._degraded_requests.discard(scoped)

    def _bind_compatibility_events(self):
        self._subscriptions.append(self.events.subscribe('state', self._compat))
        mapping = {
            'turn.started': (RuntimeState.UNDERSTANDING, 'turn_started', True),
            'turn.needs_approval': (RuntimeState.NEEDS_APPROVAL, 'approval_required', False),
            'turn.cancelled': (RuntimeState.IDLE, 'owner_cancelled', False),
            'turn.failed': (RuntimeState.ERROR, 'turn_failed', False),
            'approval.approved': (RuntimeState.TOOL_ACTION, 'approval_approved', False),
            'emergency_stop': (RuntimeState.ERROR, 'emergency_stop', False),
            'p10.emergency_stop': (RuntimeState.ERROR, 'emergency_stop', False),
        }
        for name, (target, reason, activate) in mapping.items():
            self._subscriptions.append(self.events.subscribe(name, lambda event, t=target, r=reason, a=activate: self._safe_transition(t, r, event, activate_request=a)))
        voice_mapping = {
            'voice.listening.started': (RuntimeState.LISTENING, 'voice_listening'),
            'voice.tts.started': (RuntimeState.RESPONDING, 'voice_tts_started'),
            'voice.tts.completed': (RuntimeState.ACTIVE, 'voice_tts_completed'),
            'voice.tts.failed': (RuntimeState.WARNING, 'voice_tts_failed'),
            'voice.stt.failed': (RuntimeState.WARNING, 'voice_stt_failed'),
            'voice.approval.required': (RuntimeState.NEEDS_APPROVAL, 'voice_approval_required'),
            'voice.session.stopped': (RuntimeState.IDLE, 'voice_session_stopped'),
        }
        for name, (target, reason) in voice_mapping.items():
            self._subscriptions.append(self.events.subscribe(name, lambda event, t=target, r=reason: self._on_voice_state(t, r, event)))
        self._subscriptions.append(self.events.subscribe('approval.required', self._on_approval_required))
        self._subscriptions.append(self.events.subscribe('automation.started', self._on_background_started))
        self._subscriptions.append(self.events.subscribe('workflow.started', self._on_background_started))
        self._subscriptions.append(self.events.subscribe('tool.unverified', self._on_tool_unverified))
        self._subscriptions.append(self.events.subscribe('turn.completed', self._on_turn_completed))

    def close(self):
        for unsubscribe in self._subscriptions:
            unsubscribe()
        self._subscriptions.clear()
        with self._lock:
            self._degraded_requests.clear()
            self._retired_request_ids.clear()
