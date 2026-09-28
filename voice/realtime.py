from __future__ import annotations

from dataclasses import replace

from voice.full_duplex import FullDuplexVoiceSession
from voice.intelligence import AudioDeviceManager


class RealtimeVoiceSession:
    """Canonical Stage 3 voice facade.

    Provider-native speech-to-speech can be useful transport technology, but it
    must not become a second assistant, tool, approval, or conversation authority.
    The production facade therefore always uses the provider-agnostic
    STT -> CanonicalTurnRuntime -> canonical answer -> TTS path. Provider-specific
    realtime classes remain compatibility/qualification code only and are not
    selected by the Personal AI runtime.
    """

    def __init__(self, models, executor, events=None):
        self.models = models
        self.executor = executor
        self.events = events
        self.devices = AudioDeviceManager()
        self.backend = self._make_backend(models.settings)
        self._refresh_mode()

    def _make_backend(self, settings):
        backend = FullDuplexVoiceSession(self.models, self.executor, self.events)
        backend.input_device_name = getattr(settings, 'voice_input_device', '')
        backend.output_device_name = getattr(settings, 'voice_output_device', '')
        return backend

    def _refresh_mode(self):
        self.mode = 'canonical-stt-runtime-tts'

    @property
    def thread(self):
        return getattr(self.backend, 'thread', None)

    @property
    def connected(self):
        return getattr(self.backend, 'connected', bool(self.thread and self.thread.is_alive()))

    @property
    def running(self):
        return bool(getattr(self.backend, 'running', bool(self.thread and self.thread.is_alive())))

    def start(self):
        return self.backend.start()

    def stop(self):
        return self.backend.stop()

    def barge_in(self):
        handler = getattr(self.backend, 'barge_in', None)
        if callable(handler):
            return handler()
        legacy = getattr(self.backend, 'cancel_response', None)
        if callable(legacy):
            legacy()
            return {'interrupted': True, 'request_id': None, 'canonical_turn_cancelled': False}
        return {'interrupted': False, 'request_id': None, 'canonical_turn_cancelled': False}

    def list_audio_devices(self):
        return self.devices.list()

    def select_audio_devices(self, *, input_name: str | None = None, output_name: str | None = None, restart: bool = True):
        """Select microphone/speaker by name, optionally restarting an active session."""
        was_running = self.running
        if was_running:
            self.stop()
        settings = replace(
            self.models.settings,
            voice_input_device=(input_name if input_name is not None else self.models.settings.voice_input_device),
            voice_output_device=(output_name if output_name is not None else self.models.settings.voice_output_device),
        )
        self.backend = self._make_backend(settings)
        self._refresh_mode()
        if was_running and restart:
            self.start()
        if self.events:
            self.events.emit(
                'voice.devices.changed',
                input_device=getattr(settings, 'voice_input_device', ''),
                output_device=getattr(settings, 'voice_output_device', ''),
                restarted=bool(was_running and restart),
            )
        return {
            'input_device': getattr(settings, 'voice_input_device', ''),
            'output_device': getattr(settings, 'voice_output_device', ''),
            'mode': self.mode,
        }

    def __getattr__(self, name):
        return getattr(self.backend, name)
