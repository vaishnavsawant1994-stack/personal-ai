from __future__ import annotations

import inspect
import io
import queue
import tempfile
import threading
import uuid
from pathlib import Path

from agent.executor import ConfirmationRequired, ExecutionCancelled
from voice.intelligence import AdaptiveVoiceActivity, AudioDeviceManager, SemanticEndpointDetector, VoiceProfile, resample_for_rate


class FullDuplexVoiceSession:
    """Provider-agnostic continuous voice adapter over the canonical runtime."""

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
        self._current_request_id: str | None = None
        self._q = queue.Queue(maxsize=256)
        self.thread = None
        self._play_thread = None
        self._play_cancel: threading.Event | None = None
        self._response_thread = None
        self._lifecycle_lock = threading.RLock()
        self._session_stopped_emitted = False
        self.metrics = {
            'utterances': 0,
            'barge_ins': 0,
            'dropped_audio_blocks': 0,
            'noise_floor': self.vad.noise_floor,
            'voice_threshold': self.vad.threshold,
        }

    @staticmethod
    def _drain(q):
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            pass

    def _emit(self, name, *, request_id=None, **kw):
        if self.events:
            payload = dict(kw)
            if request_id:
                payload['request_id'] = request_id
            self.events.emit(name, **payload)

    def _emit_session_stopped_once(self, request_id: str | None = None):
        with self._lifecycle_lock:
            if self._session_stopped_emitted:
                return
            self._session_stopped_emitted = True
            scoped_request_id = request_id or self._current_request_id
        self._emit('voice.session.stopped', request_id=scoped_request_id)

    def _is_current(self, request_id: str) -> bool:
        with self._lifecycle_lock:
            return self._current_request_id == request_id

    @property
    def running(self) -> bool:
        with self._lifecycle_lock:
            thread = self.thread
            return bool(thread and thread.is_alive() and not self._stop.is_set())

    def _cancel_canonical_turn(self, request_id: str | None):
        cancel = getattr(self.executor, 'cancel_turn', None)
        if not request_id or not callable(cancel):
            return None
        try:
            parameters = inspect.signature(cancel).parameters.values()
            supports_device = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters) or any(
                p.name == 'device_id' for p in parameters
            )
        except (TypeError, ValueError):
            supports_device = True
        if supports_device:
            return cancel(request_id, device_id='desktop')
        return cancel(request_id)

    def _canonical_chat(self, text, cancel_event, request_id):
        """Call canonical runtime kwargs when supported; retain legacy test adapter compatibility."""
        chat = self.executor.chat
        try:
            parameters = inspect.signature(chat).parameters.values()
            supports_runtime_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters)
        except (TypeError, ValueError):
            supports_runtime_kwargs = True
        if not supports_runtime_kwargs:
            return chat(text, cancel_event=cancel_event)
        return chat(
            text,
            request_id=request_id,
            device_id='desktop',
            surface='desktop-voice',
            input_modality='voice',
            cancel_event=cancel_event,
        )

    def start(self):
        with self._lifecycle_lock:
            if self.thread and self.thread.is_alive():
                return
            self._drain(self._q)
            self._barge.clear()
            self._turn_cancel = None
            self._play_cancel = None
            self._current_request_id = None
            self._stop.clear()
            self._session_stopped_emitted = False
            self.thread = threading.Thread(target=self._run, daemon=True, name='personal-ai-full-duplex')
            self.thread.start()

    def stop(self):
        with self._lifecycle_lock:
            self._stop.set()
            self._barge.set()
            cancel_event = self._turn_cancel
            play_cancel = self._play_cancel
            request_id = self._current_request_id
            if cancel_event:
                cancel_event.set()
            if play_cancel:
                play_cancel.set()
            workers = (self._response_thread, self._play_thread, self.thread)
        if cancel_event is not None and request_id:
            try:
                self._cancel_canonical_turn(request_id)
            except Exception as exc:
                self._emit('voice.turn.cancel_failed', request_id=request_id, error_type=type(exc).__name__)
        for worker in workers:
            if worker and worker is not threading.current_thread():
                worker.join(timeout=3)
        self._drain(self._q)
        with self._lifecycle_lock:
            self._turn_cancel = None
            self._current_request_id = None
            if self._response_thread and not self._response_thread.is_alive():
                self._response_thread = None
            if self._play_thread and not self._play_thread.is_alive():
                self._play_thread = None
                self._play_cancel = None
            if self.thread and not self.thread.is_alive():
                self.thread = None
        self._emit_session_stopped_once(request_id=request_id)

    def barge_in(self):
        with self._lifecycle_lock:
            request_id = self._current_request_id
            cancel_event = self._turn_cancel
            play_cancel = self._play_cancel
            play_active = bool(self._play_thread and self._play_thread.is_alive())
            response_active = bool(self._response_thread and self._response_thread.is_alive())
        active = bool(cancel_event is not None or play_cancel is not None or play_active or response_active)
        if not active:
            return {'interrupted': False, 'request_id': request_id, 'canonical_turn_cancelled': False}
        self._barge.set()
        if cancel_event is not None:
            cancel_event.set()
        if play_cancel is not None:
            play_cancel.set()
        canonical_turn_cancelled = False
        if cancel_event is not None and request_id:
            try:
                turn = self._cancel_canonical_turn(request_id)
                canonical_turn_cancelled = bool(turn and turn.get('status') == 'cancelled') if isinstance(turn, dict) else False
            except Exception as exc:
                self._emit('voice.turn.cancel_failed', request_id=request_id, error_type=type(exc).__name__)
        self.metrics['barge_ins'] += 1
        self._emit(
            'voice.barge_in',
            request_id=request_id,
            canonical_turn_cancelled=canonical_turn_cancelled,
            metrics=dict(self.metrics),
        )
        return {
            'interrupted': True,
            'request_id': request_id,
            'canonical_turn_cancelled': canonical_turn_cancelled,
        }

    def _barge_in(self):
        """Compatibility alias for older probes; owner/UI code uses barge_in()."""
        return self.barge_in()

    def _play(self, wav: bytes, request_id: str, interrupt_event: threading.Event):
        completed = False
        try:
            if interrupt_event.is_set() or self._stop.is_set() or not self._is_current(request_id):
                if not interrupt_event.is_set():
                    self._emit('voice.output.stale_ignored', request_id=request_id, output_event='tts_before_play')
                return
            import numpy as np
            import sounddevice as sd
            import soundfile as sf

            audio, sr = sf.read(io.BytesIO(wav), dtype='float32')
            audio = resample_for_rate(audio, self.profile.speaking_rate)
            output_device = self.devices.resolve(self.output_device_name, kind='output') if self.output_device_name else None
            channels = 1 if getattr(audio, 'ndim', 1) == 1 else audio.shape[1]
            stream = sd.OutputStream(samplerate=sr, channels=channels, dtype='float32', device=output_device)
            stream.start()
            self._emit('voice.tts.started', request_id=request_id)
            step = max(256, int(sr * 0.035))
            try:
                for index in range(0, len(audio), step):
                    if interrupt_event.is_set() or self._stop.is_set() or not self._is_current(request_id):
                        break
                    stream.write(np.asarray(audio[index:index + step], dtype='float32'))
                else:
                    completed = True
            finally:
                stream.stop()
                stream.close()
        except Exception as exc:
            self._emit('voice.tts.failed', request_id=request_id, error_type=type(exc).__name__)
        finally:
            if completed and self._is_current(request_id):
                self._emit('voice.tts.completed', request_id=request_id)
            elif not self._stop.is_set() and interrupt_event.is_set():
                self._emit('voice.playback.interrupted', request_id=request_id)
            if not self._stop.is_set() and self._is_current(request_id):
                self._emit('voice.listening.started', request_id=request_id, source='desktop-voice')
            with self._lifecycle_lock:
                if self._play_cancel is interrupt_event:
                    self._play_cancel = None
                if self._play_thread is threading.current_thread():
                    self._play_thread = None

    def _respond(self, text, cancel_event, request_id=None):
        request_id = str(request_id or uuid.uuid4())
        with self._lifecycle_lock:
            if self._current_request_id is None:
                self._current_request_id = request_id
        try:
            answer = self._canonical_chat(text, cancel_event, request_id)
            if cancel_event.is_set() or self._stop.is_set() or not self._is_current(request_id):
                self._emit('voice.output.stale_ignored', request_id=request_id, output_event='canonical_reply')
                return
            self._emit('voice.reply', request_id=request_id, text=answer, source='desktop-voice')
            try:
                wav = self.models.synthesize(answer)
            except Exception as exc:
                self._emit('voice.tts.failed', request_id=request_id, error_type=type(exc).__name__)
                if not self._stop.is_set() and self._is_current(request_id):
                    self._emit('voice.listening.started', request_id=request_id, source='desktop-voice')
                return
            if cancel_event.is_set() or self._stop.is_set() or not self._is_current(request_id):
                self._emit('voice.output.stale_ignored', request_id=request_id, output_event='tts_after_synthesis')
                return
            play_cancel = threading.Event()
            play_thread = threading.Thread(
                target=self._play,
                args=(wav, request_id, play_cancel),
                daemon=True,
                name='personal-ai-tts',
            )
            with self._lifecycle_lock:
                if cancel_event.is_set() or self._stop.is_set() or self._current_request_id != request_id:
                    stale_before_play = True
                else:
                    stale_before_play = False
                    self._play_cancel = play_cancel
                    self._play_thread = play_thread
            if stale_before_play:
                self._emit('voice.output.stale_ignored', request_id=request_id, output_event='tts_before_play_thread')
                return
            play_thread.start()
        except ConfirmationRequired as exc:
            self._emit(
                'voice.approval.required',
                request_id=request_id,
                approval_id=exc.approval_id,
                tool=exc.tool_name,
                source='desktop-voice',
            )
        except ExecutionCancelled:
            self._emit('voice.turn.cancelled', request_id=request_id, source='desktop-voice')
            if not self._stop.is_set() and self._is_current(request_id):
                self._emit('voice.listening.started', request_id=request_id, source='desktop-voice')
        except Exception as exc:
            self._emit('voice.turn.error', request_id=request_id, error_type=type(exc).__name__, source='desktop-voice')
            if not self._stop.is_set() and self._is_current(request_id):
                self._emit('voice.listening.started', request_id=request_id, source='desktop-voice')
        finally:
            with self._lifecycle_lock:
                if self._turn_cancel is cancel_event:
                    self._turn_cancel = None

    def _run(self):
        try:
            import numpy as np
            import sounddevice as sd
            import soundfile as sf
        except Exception as exc:
            self._emit('voice.session.error', error_type=type(exc).__name__)
            self._emit_session_stopped_once()
            return

        speech = []
        speaking = False
        block_seconds = self.block / float(self.samplerate)
        input_device = None
        try:
            if self.input_device_name:
                input_device = self.devices.resolve(self.input_device_name, kind='input')
        except Exception as exc:
            self._emit('voice.session.error', error_type=type(exc).__name__)
            self._emit_session_stopped_once()
            return

        def cb(indata, frames, time_info, status):
            if self._stop.is_set():
                return
            try:
                self._q.put_nowait(indata.copy())
            except queue.Full:
                self.metrics['dropped_audio_blocks'] += 1

        try:
            with sd.InputStream(
                samplerate=self.samplerate,
                channels=1,
                dtype='float32',
                blocksize=self.block,
                callback=cb,
                device=input_device,
            ):
                self._emit('voice.listening.started', source='desktop-voice')
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
                                self.barge_in()
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
                            self._emit('voice.transcription.started', source='desktop-voice')
                            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as file:
                                path = Path(file.name)
                            sf.write(path, audio, self.samplerate)
                            try:
                                text = self.models.transcribe(path)
                            except Exception as exc:
                                self._emit('voice.stt.failed', error_type=type(exc).__name__, source='desktop-voice')
                                self._emit('voice.listening.started', source='desktop-voice')
                                continue
                            finally:
                                path.unlink(missing_ok=True)
                            if not text.strip():
                                self._emit('voice.stt.empty', source='desktop-voice')
                                self._emit('voice.listening.started', source='desktop-voice')
                                continue
                            request_id = str(uuid.uuid4())
                            self.metrics['utterances'] += 1
                            self._emit(
                                'voice.transcript',
                                request_id=request_id,
                                text=text,
                                final=True,
                                source='desktop-voice',
                                metrics=dict(self.metrics),
                            )
                            cancel_event = threading.Event()
                            with self._lifecycle_lock:
                                previous = self._turn_cancel
                                if previous:
                                    previous.set()
                                self._barge.clear()
                                self._turn_cancel = cancel_event
                                self._current_request_id = request_id
                            response_thread = threading.Thread(
                                target=self._respond,
                                args=(text, cancel_event, request_id),
                                daemon=True,
                                name='personal-ai-voice-turn',
                            )
                            with self._lifecycle_lock:
                                self._response_thread = response_thread
                            response_thread.start()
        except Exception as exc:
            self._emit('voice.session.error', error_type=type(exc).__name__)
            # A fatal capture-stream failure terminates the voice session. Use the
            # same stop path as an owner stop so no canonical response/tool work can
            # survive a dead microphone worker.
            self.stop()
        finally:
            self._emit_session_stopped_once()
