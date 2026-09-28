from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class GateDecision:
    phase: str
    allowed: bool
    reason: str
    prerequisites: tuple[str, ...]


class TrustGate:
    """Fail-closed activation gate for post-P3 capabilities.

    Implementation may exist before qualification, but consequential/autonomous
    execution must not become active merely because code is present.
    """

    PREREQUISITES = {
        'p4': (),
        'p5': (),
        'p6': ('p3.permissions', 'p3.automation'),
        'p7': ('p3.permissions',),
        'p8': ('p3.continuity',),
        'p9': ('p3.permissions', 'p3.reliability'),
        'p10': ('p3.permissions', 'p3.automation', 'p3.memory', 'p3.continuity', 'p3.reliability'),
    }

    def __init__(self):
        self._proof: dict[str, bool] = {}
        self._sources: dict[str, str] = {}
        self._lock = RLock()

    def record_external_proof(self, key: str, passed: bool, *, source: str):
        """Trusted harness/operator API. Never expose as an LLM-callable tool."""
        if not source or source.strip().lower() in {'model', 'llm', 'self'}:
            raise ValueError('qualification proof must come from an external trusted source')
        with self._lock:
            self._proof[str(key)] = bool(passed)
            self._sources[str(key)] = str(source)

    def decision(self, phase: str) -> GateDecision:
        key = str(phase).strip().lower()
        required = tuple(self.PREREQUISITES.get(key, ('unknown-phase',)))
        missing = tuple(item for item in required if not self._proof.get(item, False))
        if 'unknown-phase' in required:
            return GateDecision(key, False, 'unknown phase', required)
        if missing:
            return GateDecision(key, False, 'qualification prerequisites not proven: ' + ', '.join(missing), required)
        return GateDecision(key, True, 'prerequisites satisfied', required)

    def snapshot(self):
        with self._lock:
            return {
                phase: {
                    'allowed': self.decision(phase).allowed,
                    'reason': self.decision(phase).reason,
                    'prerequisites': list(self.decision(phase).prerequisites),
                }
                for phase in self.PREREQUISITES
            }
