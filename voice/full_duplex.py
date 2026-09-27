from __future__ import annotations

import io
import queue
import tempfile
import threading
import time
from pathlib import Path

from agent.executor import ExecutionCancelled
from voice.intelligence import AdaptiveVoiceActivity, AudioDeviceManager, SemanticEndpointDetector, VoiceProfile, resample_for_rate


class FullDuplexVoiceSession:
    """Provider-agnostic continuous voice fallback with adaptive VAD and barge-in."""

    def __init__(self, models, executor, events=None, samplerate=16000, chunk_ms=60, voice_threshold=None, utterance_end_ms=None):
        self.models = models
        self.executor = executor
        self.events = events
        self.samplerate = samplerate
        self.block = int(samplerate * chunk_ms / 1000)
        settings = getattr(models, 'settings', None)
        self.profile = VoiceProfile(
            personality=getattr(settings, 'voice_personality', 'calm, concise, warm and direct'),
            speaking_rate=float(getattr(settings, 'voice_speaking_rate', 1.0)),
            min_endpoint_ms=int(utterance_end_ms or getattr(settings, 'voice_min_endpoint_ms', 420)),
            max_endpoint_ms=int(getattr(settings, 'voice_max_endpoint_ms', 1100)),
            noise_multiplier=float(getattr(settings, 'voice_noise_multiplier', 2.4)),
            min_voice_threshold=float(voice_threshold or getattr(settings, 'voice_min_threshold', 0.008)),
            max_utterance_seconds=float(getattr(settings, 'voice_max_utterance_seconds', 45.0)),
        )
        self.input_device_name = getattr(settings, 'voice_input_device', '')
        self.output_device_name = getattr(settings, 'voice_output_device', '')
        self.devices = AudioDeviceManager()
        self.vad = AdaptiveVoiceActivity(self.profile)
        self.endpoint = SemanticEndpointDetector(self.profile)
        self._stop = threading.Event()
        self._barge = threading.Event()
        self._turn_cancel: threading.Event | None = None
        self._q = queue.Queue(maxsize=256)
        self.thread = None
        self._play_thread = None
        self._response_thread = None
        self.metrics = {
            'utterances': 0,
            'barge_ins': 0,
            'dropped_audio_blocks': 0,
            'noise_floor': self.vad.noise_floor,
            'voice_threshold': self.vad.threshold,
        }

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name='personal-ai-full-duplex')
        self.thread.start()

    def stop(self):
        self._stop.set()
        self._barge.set()
        if self._turn_cancel:
            self._turn_cancel.set()

    def _emit(self, name, **kw):
        if self.events:
            self.events.emit(name, **kw)

    def _barge_in(self):
        self._barge.set()
        if self._turn_cancel:
            self._turn_cancel.set()
        self.metrics['barge_ins'] += 1
        self._emit('voice.barge_in', metrics=dict(self.metrics))
        self._emit('state', state='listening')

    def _play(self, wav: bytes):
        try:
            import numpy as np
            import sounddevice as sd
            import soundfile as sf

            audio, sr = sf.read(io.BytesIO(wav), dtype='float32')
            audio = resample_for_rate(audio, self.profile.speaking_rate)
            self._barge.clear()
            output_device = self.devices.resolve(self.output_device_name, kind='output') if self.output_device_name else None
            channels = 1 if getattr(audio, 'ndim', 1) == 1 else audio.shape[1]
            stream = sd.OutputStream(samplerate=sr, channels=channels, dtype='float32', device=output_device)
            stream.start()
            step = max(256, int(sr * 0.035))
            for i in range(0, len(audio), step):
                if self._barge.is_set() or self._stop.is_set():
                    break
                stream.write(np.asarray(audio[i:i + step], dtype='float32'))
            stream.stop()
            stream.close()
        except Exception as exc:
            self._emit('voice.error', error=str(exc))
        finally:
            if not self._stop.is_set() and not self._barge.is_set():
                self._emit('state', state='listening')

    def _respond(self, text, cancel_event):
        try:
            self._emit('state', state='understanding')
            answer = self.executor.chat(text, cancel_event=cancel_event)
            if cancel_event.is_set() or self._stop.is_set():
                return
            self._emit('voice.reply', text=answer)
            self._emit('state', state='speaking')
            wav = self.models.synthesize(answer)
            if cancel_event.is_set() or self._stop.is_set():
                return
            self._play_thread = threading.Thread(target=self._play, args=(wav,), daemon=True, name='personal-ai-tts')
            self._play_thread.start()
        except ExecutionCancelled:
            self._emit('voice.turn.cancelled')
        except Exception as exc:
            self._emit('voice.error', error=str(exc))
            self._emit('state', state='listening')

    def _run(self):
        try:
            import numpy as np
            import sounddevice as sd
            import soundfile as sf
        except Exception as exc:
            self._emit('voice.error', error=str(exc))
            return

        speech = []
        speaking = False
        block_seconds = self.block / float(self.samplerate)
        input_device = None
        try:
            if self.input_device_name:
                input_device = self.devices.resolve(self.input_device_name, kind='input')
        except Exception as exc:
            self._emit('voice.error', error=str(exc))
            return

        def cb(indata, frames, time_info, status):
            try:
                self._q.put_nowait(indata.copy())
            except queue.Full:
                self.metrics['dropped_audio_blocks'] += 1

        with sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype='float32',
            blocksize=self.block,
            callback=cb,
            device=input_device,
        ):
            self._emit('state', state='listening')
            while not self._stop.is_set():
                try:
                    block = self._q.get(timeout=.15)
                except queue.Empty:
                    continue
                rms = float(np.sqrt(np.mean(block ** 2)))
                is_voice = self.vad.observe(rms, speech_active=speaking)
                self.metrics['noise_floor'] = round(self.vad.noise_floor, 6)
                self.metrics['voice_threshold'] = round(self.vad.threshold, 6)

                if is_voice:
                    if not speaking:
                        self.endpoint.reset()
                        if (
                            (self._play_thread and self._play_thread.is_alive())
                            or (self._response_thread and self._response_thread.is_alive())
                        ):
                            self._barge_in()
                    speech.append(block)
                    speaking = True
                    self.endpoint.update(voice=True, block_seconds=block_seconds)
                elif speaking:
                    speech.append(block)
                    if self.endpoint.update(voice=False, block_seconds=block_seconds):
                        audio = np.concatenate(speech)
                        speech = []
                        speaking = False
                        self.endpoint.reset()
                        if len(audio) < self.samplerate * .22:
                            continue
                        self._emit('state', state='understanding')
                        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as file:
                            path = Path(file.name)
                        sf.write(path, audio, self.samplerate)
                        try:
                            text = self.models.transcribe(path)
                        finally:
                            path.unlink(missing_ok=True)
                        if not text.strip():
                            self._emit('state', state='listening')
                            continue
                        self.metrics['utterances'] += 1
                        self._emit('voice.transcript', text=text, metrics=dict(self.metrics))
                        cancel_event = threading.Event()
                        self._turn_cancel = cancel_event
                        self._response_thread = threading.Thread(
                            target=self._respond,
                            args=(text, cancel_event),
                            daemon=True,
                            name='personal-ai-voice-turn',
                        )
                        self._response_thread.start()
            self._emit('state', state='idle')
