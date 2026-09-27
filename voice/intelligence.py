from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Iterable


@dataclass(frozen=True)
class VoiceProfile:
    """User-facing voice behavior independent of any one provider."""

    personality: str = "calm, concise, warm and direct"
    speaking_rate: float = 1.0
    min_endpoint_ms: int = 420
    max_endpoint_ms: int = 1100
    noise_multiplier: float = 2.4
    min_voice_threshold: float = 0.008
    max_utterance_seconds: float = 45.0

    def __post_init__(self):
        if not 0.65 <= float(self.speaking_rate) <= 1.5:
            raise ValueError("speaking_rate must be between 0.65 and 1.5")
        if self.min_endpoint_ms < 150 or self.max_endpoint_ms < self.min_endpoint_ms:
            raise ValueError("invalid endpoint timing")
        if self.noise_multiplier < 1.1:
            raise ValueError("noise_multiplier must be >= 1.1")


class AdaptiveVoiceActivity:
    """Small deterministic VAD helper used by the provider-agnostic fallback path.

    It learns a conservative background RMS while no utterance is active and raises
    the speech threshold in noisy rooms. It intentionally does not try to replace a
    provider-native semantic VAD when one is available.
    """

    def __init__(self, profile: VoiceProfile, *, initial_noise: float = 0.002):
        self.profile = profile
        self.noise_floor = max(0.0001, float(initial_noise))
        self._alpha_idle = 0.06
        self._alpha_speech = 0.005

    @property
    def threshold(self) -> float:
        return max(
            float(self.profile.min_voice_threshold),
            self.noise_floor * float(self.profile.noise_multiplier),
        )

    def observe(self, rms: float, *, speech_active: bool) -> bool:
        rms = max(0.0, float(rms))
        current_threshold = self.threshold
        is_voice = rms >= current_threshold
        alpha = self._alpha_speech if speech_active or is_voice else self._alpha_idle
        # Do not let obvious speech spikes rapidly poison the learned noise floor.
        sample = min(rms, current_threshold * 1.25) if is_voice else rms
        self.noise_floor = (1.0 - alpha) * self.noise_floor + alpha * sample
        return is_voice


class SemanticEndpointDetector:
    """Energy/timing endpoint policy for the non-streaming STT fallback.

    Longer/heavier utterances receive a slightly larger pause budget, preventing
    natural mid-sentence thinking pauses from being cut off. Short utterances remain
    responsive. Provider-native semantic VAD remains preferred when configured.
    """

    def __init__(self, profile: VoiceProfile):
        self.profile = profile
        self.started_at: float | None = None
        self.last_voice_at: float | None = None
        self.voice_seconds = 0.0

    def reset(self):
        self.started_at = None
        self.last_voice_at = None
        self.voice_seconds = 0.0

    def update(self, *, voice: bool, block_seconds: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else float(now)
        if voice:
            if self.started_at is None:
                self.started_at = now
            self.last_voice_at = now
            self.voice_seconds += max(0.0, float(block_seconds))
            return False
        if self.started_at is None or self.last_voice_at is None:
            return False
        if now - self.started_at >= float(self.profile.max_utterance_seconds):
            return True
        endpoint_ms = self.profile.min_endpoint_ms + min(
            self.profile.max_endpoint_ms - self.profile.min_endpoint_ms,
            int(self.voice_seconds * 75),
        )
        return (now - self.last_voice_at) * 1000.0 >= endpoint_ms


class AudioDeviceManager:
    """Resolve configured microphone/speaker names without pinning platform indexes."""

    @staticmethod
    def _rows(devices: Iterable) -> list[dict]:
        rows = []
        for index, item in enumerate(devices):
            row = dict(item) if not isinstance(item, dict) else item
            rows.append({"index": index, **row})
        return rows

    def list(self) -> list[dict]:
        import sounddevice as sd

        return self._rows(sd.query_devices())

    def resolve(self, name: str | None, *, kind: str, devices: Iterable | None = None):
        if kind not in {"input", "output"}:
            raise ValueError("kind must be input or output")
        if not name:
            return None
        rows = self._rows(devices) if devices is not None else self.list()
        needle = str(name).strip().lower()
        capacity_key = "max_input_channels" if kind == "input" else "max_output_channels"
        eligible = [
            row
            for row in rows
            if needle in str(row.get("name", "")).lower() and int(row.get(capacity_key, 0)) > 0
        ]
        if not eligible:
            raise ValueError(f"Configured {kind} audio device was not found: {name}")
        exact = [row for row in eligible if str(row.get("name", "")).strip().lower() == needle]
        return (exact or eligible)[0]["index"]


def resample_for_rate(audio, rate: float):
    """Dependency-light playback rate adjustment for the fallback TTS path."""

    rate = float(rate)
    if math.isclose(rate, 1.0, rel_tol=1e-3):
        return audio
    import numpy as np

    if len(audio) < 2:
        return audio
    target = max(1, int(len(audio) / rate))
    old_x = np.linspace(0.0, 1.0, num=len(audio), endpoint=True)
    new_x = np.linspace(0.0, 1.0, num=target, endpoint=True)
    if getattr(audio, "ndim", 1) == 1:
        return np.interp(new_x, old_x, audio).astype("float32")
    channels = [np.interp(new_x, old_x, audio[:, i]) for i in range(audio.shape[1])]
    return np.stack(channels, axis=1).astype("float32")
