from __future__ import annotations

from dataclasses import replace

from voice.full_duplex import FullDuplexVoiceSession
from voice.intelligence import AudioDeviceManager
from voice.openai_realtime import OpenAIRealtimeVoiceSession


class RealtimeVoiceSession:
    """Select provider-native realtime when configured; keep a hardened fallback."""

    def __init__(self, models, executor, events=None):
        self.models = models
        self.executor = executor
        self.events = events
        self.devices = AudioDeviceManager()
        self.backend = self._make_backend(models.settings)
        self._refresh_mode()

    def _make_backend(self, settings):
        native = OpenAIRealtimeVoiceSession(settings, self.events, executor=self.executor)
        if native.enabled:
            return native
        fallback = FullDuplexVoiceSession(self.models, self.executor, self.events)
        fallback.input_device_name = getattr(settings, 'voice_input_device', '')
        fallback.output_device_name = getattr(settings, 'voice_output_device', '')
        return fallback

    def _refresh_mode(self):
        self.mode = 'openai-realtime' if isinstance(self.backend, OpenAIRealtimeVoiceSession) else 'stt-llm-tts-fallback'

    @property
    def thread(self):
        return getattr(self.backend, 'thread', None)

    @property
    def connected(self):
        return getattr(self.backend, 'connected', False)

    def start(self):
        return self.backend.start()

    def stop(self):
        return self.backend.stop()

    def list_audio_devices(self):
        return self.devices.list()

    def select_audio_devices(self, *, input_name: str | None = None, output_name: str | None = None, restart: bool = True):
        """Select microphone/speaker by name, optionally restarting an active session.

        The setting is runtime-scoped; persistent preferences can store the selected
        names separately and apply them at the next application start.
        """
        was_running = bool(self.thread and self.thread.is_alive())
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
