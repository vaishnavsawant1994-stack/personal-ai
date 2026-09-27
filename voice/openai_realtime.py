from __future__ import annotations

import base64
import json
import queue
import threading
import time
from urllib.parse import quote

from voice.intelligence import AudioDeviceManager, VoiceProfile
from voice.realtime_tools import RealtimeToolBridge


class OpenAIRealtimeVoiceSession:
    """Provider-native speech-to-speech session over the GA Realtime WebSocket API."""

    def __init__(self, settings, events=None, executor=None):
        self.settings = settings
        self.events = events
        self.thread = None
        self._stop = threading.Event()
        self._ws = None
        self._audio_q = queue.Queue(maxsize=128)
        self._play_q = queue.Queue(maxsize=256)
        self._response_active = False
        self._speaking_emitted = False
        self._connected = False
        self.tool_bridge = RealtimeToolBridge(executor, events) if executor else None
        self.devices = AudioDeviceManager()
        self.profile = VoiceProfile(
            personality=getattr(settings, 'voice_personality', 'calm, concise, warm and direct'),
            speaking_rate=float(getattr(settings, 'voice_speaking_rate', 1.0)),
            min_endpoint_ms=int(getattr(settings, 'voice_min_endpoint_ms', 420)),
            max_endpoint_ms=int(getattr(settings, 'voice_max_endpoint_ms', 1100)),
            noise_multiplier=float(getattr(settings, 'voice_noise_multiplier', 2.4)),
            min_voice_threshold=float(getattr(settings, 'voice_min_threshold', 0.008)),
            max_utterance_seconds=float(getattr(settings, 'voice_max_utterance_seconds', 45.0)),
        )
        self.metrics = {
            'connect_attempts': 0,
            'reconnects': 0,
            'audio_chunks_in': 0,
            'audio_chunks_out': 0,
            'response_count': 0,
            'barge_ins': 0,
            'last_connect_ms': None,
            'last_response_ms': None,
            'last_error': None,
        }
        self._connect_started = None
        self._speech_stopped_at = None

    @property
    def enabled(self):
        return bool(self.settings.openai_api_key and self.settings.realtime_provider in {'auto', 'openai'})

    @property
    def connected(self):
        return self._connected

    def _emit(self, name, **kw):
        if self.events:
            self.events.emit(name, **kw)

    def url(self):
        return f"wss://api.openai.com/v1/realtime?model={quote(self.settings.realtime_model)}"

    def headers(self):
        headers = [f"Authorization: Bearer {self.settings.openai_api_key}"]
        if self.settings.realtime_safety_identifier:
            headers.append(f"OpenAI-Safety-Identifier: {self.settings.realtime_safety_identifier}")
        return headers

    def session_update(self):
        instructions = (
            f"{self.settings.realtime_instructions}\n"
            f"Voice personality: {self.profile.personality}. "
            f"Prefer a natural conversational speaking rate near {self.profile.speaking_rate:.2f}x. "
            "Do not narrate internal tool mechanics. Stop immediately when the user interrupts."
        )
        session = {
            'type': 'realtime',
            'model': self.settings.realtime_model,
            'instructions': instructions,
            'output_modalities': ['audio'],
            'reasoning': {'effort': self.settings.realtime_reasoning_effort},
            'audio': {
                'input': {
                    'format': {'type': 'audio/pcm', 'rate': self.settings.realtime_sample_rate},
                    'turn_detection': {'type': 'semantic_vad'},
                },
                'output': {
                    'format': {'type': 'audio/pcm'},
                    'voice': self.settings.realtime_voice,
                },
            },
        }
        if self.tool_bridge:
            session['tools'] = self.tool_bridge.definitions()
        return {'type': 'session.update', 'session': session}

    @staticmethod
    def append_event(pcm16: bytes):
        return {'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm16).decode('ascii')}

    def cancel_response(self):
        if self._ws and self._response_active:
            try:
                self._ws.send(json.dumps({'type': 'response.cancel'}))
            except Exception:
                pass
        self._response_active = False
        self._speaking_emitted = False
        self._drain(self._play_q)
        if self.tool_bridge:
            self.tool_bridge.cancel_unapproved(reason='voice_barge_in')
        self.metrics['barge_ins'] += 1
        self._emit('voice.barge_in', metrics=dict(self.metrics))

    @staticmethod
    def _drain(q):
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            pass

    def _send_tool_output(self, call_id, result):
        if not self._ws:
            return
        self._ws.send(
            json.dumps(
                {
                    'type': 'conversation.item.create',
                    'item': {
                        'type': 'function_call_output',
                        'call_id': call_id,
                        'output': json.dumps(result, default=str),
                    },
                }
            )
        )
        self._ws.send(json.dumps({'type': 'response.create'}))

    def approve_tool(self, call_id):
        if not self.tool_bridge:
            raise RuntimeError('Realtime tools are unavailable')
        result = self.tool_bridge.approve(call_id)
        self._send_tool_output(call_id, result)
        return result

    def reject_tool(self, call_id):
        if not self.tool_bridge:
            raise RuntimeError('Realtime tools are unavailable')
        result = self.tool_bridge.reject(call_id)
        self._send_tool_output(call_id, result)
        return result

    def handle_event(self, event: dict):
        event_type = event.get('type', '')
        if event_type == 'session.created':
            self._connected = True
            if self._connect_started:
                self.metrics['last_connect_ms'] = round((time.monotonic() - self._connect_started) * 1000, 1)
            self._emit('voice.realtime.connected', model=self.settings.realtime_model, metrics=dict(self.metrics))
        elif event_type == 'response.created':
            self._response_active = True
            self._speaking_emitted = False
            self.metrics['response_count'] += 1
            if self._speech_stopped_at:
                self.metrics['last_response_ms'] = round((time.monotonic() - self._speech_stopped_at) * 1000, 1)
            self._emit('state', state='thinking')
        elif event_type == 'response.output_audio.delta':
            if not self._speaking_emitted:
                self._speaking_emitted = True
                self._emit('state', state='speaking')
            try:
                self._play_q.put_nowait(base64.b64decode(event.get('delta', '')))
                self.metrics['audio_chunks_out'] += 1
            except (ValueError, queue.Full):
                pass
        elif event_type == 'response.output_audio_transcript.delta':
            if event.get('delta'):
                self._emit('voice.reply.delta', text=event['delta'])
        elif event_type == 'response.function_call_arguments.done' and self.tool_bridge:
            call_id = event.get('call_id') or event.get('item_id') or ''
            name = event.get('name', '')
            result = self.tool_bridge.invoke(call_id, name, event.get('arguments', '{}'))
            if result.get('status') != 'approval_required':
                self._send_tool_output(call_id, result)
        elif event_type == 'response.done':
            self._response_active = False
            self._speaking_emitted = False
            self._emit('state', state='listening')
        elif event_type == 'input_audio_buffer.speech_started':
            if self._response_active:
                self.cancel_response()
            self._emit('state', state='listening')
        elif event_type == 'input_audio_buffer.speech_stopped':
            self._speech_stopped_at = time.monotonic()
            self._emit('state', state='understanding')
        elif event_type == 'error':
            self.metrics['last_error'] = str(event.get('error', event))
            self._emit('voice.error', error=self.metrics['last_error'])

    def start(self):
        if not self.enabled:
            raise RuntimeError('OpenAI Realtime is not configured')
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name='personal-ai-realtime')
        self.thread.start()

    def stop(self):
        self._stop.set()
        self._connected = False
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass
        self._drain(self._audio_q)
        self._drain(self._play_q)
        if self.tool_bridge:
            self.tool_bridge.cancel_unapproved(reason='voice_stopped')
        self._emit('state', state='idle')

    def _run(self):
        import websocket

        backoff = 1.0
        first = True
        while not self._stop.is_set():
            self.metrics['connect_attempts'] += 1
            if not first:
                self.metrics['reconnects'] += 1
            first = False
            self._connect_started = time.monotonic()
            try:
                self._run_once(websocket)
                backoff = 1.0
            except Exception as exc:
                self._connected = False
                self.metrics['last_error'] = str(exc)
                self._emit('voice.realtime.disconnected', error=str(exc), metrics=dict(self.metrics))
                if self._stop.wait(backoff):
                    break
                backoff = min(backoff * 2, 15.0)

    def _run_once(self, websocket):
        opened = threading.Event()

        def on_open(ws):
            self._ws = ws
            ws.send(json.dumps(self.session_update()))
            opened.set()

        def on_message(ws, message):
            try:
                self.handle_event(json.loads(message))
            except Exception as exc:
                self._emit('voice.error', error=f'realtime event: {exc}')

        def on_error(ws, error):
            self._emit('voice.error', error=f'realtime transport: {error}')

        def on_close(ws, status, message):
            self._connected = False

        app = websocket.WebSocketApp(
            self.url(),
            header=self.headers(),
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self._ws = app
        network = threading.Thread(
            target=lambda: app.run_forever(ping_interval=20, ping_timeout=10),
            daemon=True,
        )
        network.start()
        if not opened.wait(15):
            raise RuntimeError('Realtime WebSocket connection timed out')
        self._emit('state', state='listening')
        threading.Thread(target=self._audio_io, daemon=True, name='personal-ai-realtime-audio').start()
        while not self._stop.is_set() and network.is_alive():
            try:
                chunk = self._audio_q.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                app.send(json.dumps(self.append_event(chunk)))
                self.metrics['audio_chunks_in'] += 1
            except Exception:
                break
        try:
            app.close()
        except Exception:
            pass
        network.join(timeout=3)

    def _audio_io(self):
        import sounddevice as sd

        rate = self.settings.realtime_sample_rate
        input_device = self.devices.resolve(self.settings.voice_input_device, kind='input') if self.settings.voice_input_device else None
        output_device = self.devices.resolve(self.settings.voice_output_device, kind='output') if self.settings.voice_output_device else None

        def input_cb(indata, frames, time_info, status):
            if self._stop.is_set():
                return
            try:
                self._audio_q.put_nowait(bytes(indata))
            except queue.Full:
                pass

        with sd.RawInputStream(
            samplerate=rate,
            channels=1,
            dtype='int16',
            blocksize=max(240, int(rate * .02)),
            callback=input_cb,
            device=input_device,
        ), sd.RawOutputStream(
            samplerate=rate,
            channels=1,
            dtype='int16',
            blocksize=max(240, int(rate * .02)),
            device=output_device,
        ) as output:
            while not self._stop.is_set() and self._ws:
                try:
                    chunk = self._play_q.get(timeout=.05)
                except queue.Empty:
                    continue
                if chunk:
                    output.write(chunk)
