from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from agent.executor import ExecutionCancelled
from voice.full_duplex import FullDuplexVoiceSession
from voice.realtime import RealtimeVoiceSession


class Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append((name, payload))


class Models:
    def __init__(self):
        self.settings = SimpleNamespace(
            voice_personality='calm',
            voice_speaking_rate=1.0,
            voice_min_endpoint_ms=420,
            voice_max_endpoint_ms=1100,
            voice_noise_multiplier=2.4,
            voice_min_threshold=0.008,
            voice_max_utterance_seconds=45.0,
            voice_input_device='',
            voice_output_device='',
        )

    def synthesize(self, text):
        raise AssertionError('cancelled turn must never synthesize stale speech')


class CancelAfterReturnExecutor:
    def chat(self, text, cancel_event=None):
        cancel_event.set()
        return 'stale response'


class CancelledExecutor:
    def chat(self, text, cancel_event=None):
        raise ExecutionCancelled('cancelled')


class CanonicalCancelProbe:
    def __init__(self):
        self.cancelled = []

    def chat(self, text, cancel_event=None, **kwargs):
        return 'ok'

    def cancel_turn(self, request_id, device_id=None):
        self.cancelled.append((request_id, device_id))
        return {'request_id': request_id, 'status': 'cancelled'}


class AliveThread:
    def is_alive(self):
        return True


def test_cancelled_turn_suppresses_late_reply_and_tts_without_legacy_state_writer():
    events = Events()
    session = FullDuplexVoiceSession(Models(), CancelAfterReturnExecutor(), events)
    cancel = threading.Event()
    session._turn_cancel = cancel

    session._respond('hello', cancel)

    names = [name for name, _ in events.rows]
    assert 'voice.reply' not in names
    assert 'voice.output.stale_ignored' in names
    assert 'state' not in names
    assert session._turn_cancel is None


def test_execution_cancelled_returns_to_factual_listening_lifecycle():
    events = Events()
    session = FullDuplexVoiceSession(Models(), CancelledExecutor(), events)
    cancel = threading.Event()
    session._turn_cancel = cancel

    session._respond('hello', cancel)

    names = [name for name, _ in events.rows]
    assert 'voice.turn.cancelled' in names
    assert 'voice.listening.started' in names
    assert 'state' not in names
    assert session._turn_cancel is None


def test_stop_cancels_turn_drains_audio_and_emits_factual_session_stop():
    events = Events()
    session = FullDuplexVoiceSession(Models(), CancelAfterReturnExecutor(), events)
    cancel = threading.Event()
    session._turn_cancel = cancel
    session._q.put_nowait(b'old-audio')

    session.stop()
    session.stop()

    assert cancel.is_set()
    assert session._turn_cancel is None
    assert session._q.empty()
    assert [name for name, _ in events.rows].count('voice.session.stopped') == 1
    assert not any(name == 'state' for name, _ in events.rows)


def test_public_barge_in_interrupts_and_durably_cancels_inflight_canonical_turn():
    events = Events()
    executor = CanonicalCancelProbe()
    session = FullDuplexVoiceSession(Models(), executor, events)
    cancel = threading.Event()
    session._current_request_id = 'voice-request-1'
    session._turn_cancel = cancel

    result = session.barge_in()

    assert cancel.is_set()
    assert executor.cancelled == [('voice-request-1', 'desktop')]
    assert result == {
        'interrupted': True,
        'request_id': 'voice-request-1',
        'canonical_turn_cancelled': True,
    }
    barge = next(payload for name, payload in events.rows if name == 'voice.barge_in')
    assert barge['request_id'] == 'voice-request-1'
    assert barge['canonical_turn_cancelled'] is True


def test_playback_only_barge_in_does_not_retroactively_cancel_completed_turn():
    events = Events()
    executor = CanonicalCancelProbe()
    session = FullDuplexVoiceSession(Models(), executor, events)
    session._current_request_id = 'completed-request'
    session._play_thread = AliveThread()

    result = session.barge_in()

    assert result['interrupted'] is True
    assert result['canonical_turn_cancelled'] is False
    assert executor.cancelled == []
    assert session._barge.is_set()


def test_stop_durably_cancels_inflight_canonical_voice_turn():
    executor = CanonicalCancelProbe()
    session = FullDuplexVoiceSession(Models(), executor, Events())
    cancel = threading.Event()
    session._current_request_id = 'voice-request-stop'
    session._turn_cancel = cancel

    session.stop()

    assert cancel.is_set()
    assert executor.cancelled == [('voice-request-stop', 'desktop')]
    stopped = [payload for name, payload in session.events.rows if name == 'voice.session.stopped']
    assert stopped == [{'request_id': 'voice-request-stop'}]
    assert session.running is False


def test_realtime_voice_facade_exposes_truthful_running_and_public_barge_in():
    executor = CanonicalCancelProbe()
    voice = RealtimeVoiceSession(Models(), executor, Events())
    voice.backend.thread = AliveThread()
    voice.backend._current_request_id = 'voice-request-2'
    voice.backend._turn_cancel = threading.Event()

    assert voice.running is True
    result = voice.barge_in()

    assert result['interrupted'] is True
    assert result['canonical_turn_cancelled'] is True
    assert executor.cancelled == [('voice-request-2', 'desktop')]


def test_audio_stream_failure_emits_error_and_exactly_one_factual_stop(monkeypatch):
    events = Events()
    session = FullDuplexVoiceSession(Models(), CanonicalCancelProbe(), events)

    def fail_input_stream(**kwargs):
        raise RuntimeError('no audio device')

    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(InputStream=fail_input_stream))
    session._run()
    session.stop()

    names = [name for name, _ in events.rows]
    assert 'voice.session.error' in names
    assert names.count('voice.session.stopped') == 1
    assert session.running is False


def test_barge_in_still_interrupts_output_when_durable_cancel_reports_error():
    class FailingCancelExecutor(CanonicalCancelProbe):
        def cancel_turn(self, request_id, device_id=None):
            raise RuntimeError('cancel store unavailable')

    events = Events()
    session = FullDuplexVoiceSession(Models(), FailingCancelExecutor(), events)
    cancel = threading.Event()
    session._current_request_id = 'voice-request-error'
    session._turn_cancel = cancel

    result = session.barge_in()

    assert cancel.is_set()
    assert result['interrupted'] is True
    assert result['canonical_turn_cancelled'] is False
    assert any(name == 'voice.turn.cancel_failed' for name, _ in events.rows)
    assert any(name == 'voice.barge_in' for name, _ in events.rows)


def test_desktop_voice_surfaces_use_public_runtime_lifecycle_contract():
    realtime = Path('voice/realtime.py').read_text(encoding='utf-8')
    floating = Path('desktop/floating_presence.py').read_text(encoding='utf-8')
    window = Path('ui/main_window.py').read_text(encoding='utf-8')
    benchmark = Path('capabilities/benchmark.py').read_text(encoding='utf-8')

    assert 'def running(self):' in realtime
    assert 'def barge_in(self):' in realtime
    assert "getattr(voice, 'running', False)" in floating
    assert "hasattr(voice, 'barge_in')" in floating
    assert 'running = bool(getattr(voice, "running", self.voice_running))' in window
    assert 'events.subscribe("voice.session.stopped", self._voice_session_stopped_event.emit)' in window
    assert 'events.subscribe("voice.transcript", self._voice_transcript_event.emit)' in window
    assert 'events.subscribe("voice.reply", self._voice_reply_event.emit)' in window
    assert 'self._voice_transcript_event.connect(self._on_voice_transcript)' in window
    assert 'self._voice_reply_event.connect(self._on_voice_reply)' in window
    assert 'def closeEvent(self, event):' in window
    assert 'unsubscribe()' in window
    assert "callable(getattr(self.runtime.get('voice'), 'barge_in', None))" in benchmark



def test_fatal_audio_worker_exit_cancels_inflight_canonical_turn(monkeypatch):
    events = Events()
    executor = CanonicalCancelProbe()
    session = FullDuplexVoiceSession(Models(), executor, events)
    cancel = threading.Event()
    session._current_request_id = 'voice-request-audio-failure'
    session._turn_cancel = cancel

    def fail_input_stream(**kwargs):
        raise RuntimeError('audio device disappeared')

    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(InputStream=fail_input_stream))
    session._run()

    assert cancel.is_set()
    assert executor.cancelled == [('voice-request-audio-failure', 'desktop')]
    assert session.running is False
    names = [name for name, _ in events.rows]
    assert 'voice.session.error' in names
    stopped = [payload for name, payload in events.rows if name == 'voice.session.stopped']
    assert stopped == [{'request_id': 'voice-request-audio-failure'}]



def test_desktop_qt_surfaces_marshal_worker_events_before_touching_widgets():
    window = Path('ui/main_window.py').read_text(encoding='utf-8')
    floating = Path('desktop/floating_presence.py').read_text(encoding='utf-8')

    assert '_voice_transcript_event = pyqtSignal(object)' in window
    assert '_voice_reply_event = pyqtSignal(object)' in window
    assert '_voice_session_stopped_event = pyqtSignal(object)' in window
    assert 'events.subscribe("voice.transcript", self._voice_transcript_event.emit)' in window
    assert 'events.subscribe("voice.reply", self._voice_reply_event.emit)' in window
    assert 'events.subscribe("voice.session.stopped", self._voice_session_stopped_event.emit)' in window
    assert 'events.subscribe("voice.transcript", self._on_voice_transcript)' not in window
    assert 'events.subscribe("voice.reply", self._on_voice_reply)' not in window

    assert '_runtime_state_event = pyqtSignal(object)' in floating
    assert "self._runtime_state_event.connect(self._render_state)" in floating
    assert "self.events.subscribe('runtime.state', self._runtime_state_event.emit)" in floating
    assert "self.events.subscribe('runtime.state', self._render_state)" not in floating



def test_barge_in_sets_request_scoped_playback_interrupt_before_thread_runs():
    events = Events()
    session = FullDuplexVoiceSession(Models(), CanonicalCancelProbe(), events)
    session._current_request_id = 'completed-request'
    play_cancel = threading.Event()
    session._play_cancel = play_cancel

    result = session.barge_in()

    assert result['interrupted'] is True
    assert result['canonical_turn_cancelled'] is False
    assert play_cancel.is_set()


def test_pre_start_playback_interrupt_cannot_be_cleared_by_playback_worker():
    events = Events()
    session = FullDuplexVoiceSession(Models(), CanonicalCancelProbe(), events)
    session._current_request_id = 'completed-request'
    play_cancel = threading.Event()
    play_cancel.set()
    session._play_cancel = play_cancel

    session._play(b'not-decoded-because-interrupted', 'completed-request', play_cancel)

    names = [name for name, _ in events.rows]
    assert 'voice.playback.interrupted' in names
    assert 'voice.tts.started' not in names
    assert session._play_cancel is None


def test_playback_worker_never_clears_shared_barge_state_after_start():
    source = Path('voice/full_duplex.py').read_text(encoding='utf-8')
    play = source[source.index('    def _play('):source.index('    def _respond(')]
    assert 'self._barge.clear()' not in play
    assert 'interrupt_event.is_set()' in play
    assert 'self._play_cancel = play_cancel' in source
