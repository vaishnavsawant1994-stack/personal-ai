from __future__ import annotations
import queue

class VoiceRuntime:
    """Streaming-oriented audio runtime with pluggable STT/TTS providers."""
    def __init__(self,recorder=None,tts=None,events=None):
        self.recorder=recorder; self.tts=tts; self.events=events
        self.frames=queue.Queue(maxsize=128); self._running=False

    def start_listening(self):
        self._running=True
        if self.events: self.events.emit("state",state="listening")

    def stop_listening(self):
        self._running=False
        if self.events: self.events.emit("state",state="idle")

    def push_pcm(self,frame:bytes):
        if not self._running: return False
        try: self.frames.put_nowait(frame); return True
        except queue.Full: return False

    def speak(self,text:str):
        if self.events: self.events.emit("state",state="speaking")
        if self.tts: self.tts.speak(text)
        if self.events: self.events.emit("state",state="idle")
