from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from voice.openai_realtime import OpenAIRealtimeVoiceSession


def settings():
    return SimpleNamespace(
        openai_api_key='test-key',
        realtime_provider='openai',
        realtime_model='realtime-test',
        realtime_safety_identifier='',
        realtime_instructions='Be helpful.',
        realtime_reasoning_effort='low',
        realtime_sample_rate=24000,
        realtime_voice='alloy',
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


class FakeSocketApp:
    instances = []

    def __init__(self, url, header, on_open, on_message, on_error, on_close):
        self.on_open = on_open
        self.on_close = on_close
        self.closed = threading.Event()
        self.sent = []
        FakeSocketApp.instances.append(self)

    def send(self, payload):
        self.sent.append(payload)

    def close(self):
        self.closed.set()

    def run_forever(self, **kwargs):
        self.on_open(self)
        time.sleep(0.03)
        self.on_close(self, 1006, 'network drop')


class FakeWebsocketModule:
    WebSocketApp = FakeSocketApp


class InstrumentedSession(OpenAIRealtimeVoiceSession):
    def __init__(self):
        super().__init__(settings(), events=None, executor=None)
        self.audio_started = []
        self.audio_finished = []
        self.active_audio = 0
        self.max_active_audio = 0
        self.audio_lock = threading.Lock()

    def _audio_io(self, connection):
        with self.audio_lock:
            self.active_audio += 1
            self.max_active_audio = max(self.max_active_audio, self.active_audio)
            self.audio_started.append(connection)
        try:
            while not self._stop.is_set():
                with self._ws_lock:
                    if self._ws is not connection:
                        break
                time.sleep(0.002)
        finally:
            with self.audio_lock:
                self.active_audio -= 1
                self.audio_finished.append(connection)


def test_reconnect_terminates_previous_audio_worker_before_next_connection():
    session = InstrumentedSession()
    session._run_once(FakeWebsocketModule)
    session._run_once(FakeWebsocketModule)

    assert len(session.audio_started) == 2
    assert len(session.audio_finished) == 2
    assert session.max_active_audio == 1
    assert session._audio_worker is None
    assert session._ws is None


def test_stop_clears_connection_and_is_idempotent():
    session = InstrumentedSession()
    socket = FakeSocketApp('', [], lambda *_: None, lambda *_: None, lambda *_: None, lambda *_: None)
    with session._ws_lock:
        session._ws = socket
    session._connected = True

    session.stop()
    session.stop()

    assert session.connected is False
    assert session._ws is None
    assert socket.closed.is_set()
