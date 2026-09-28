from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
import threading
import time
import uuid


class HealthState(str, Enum):
    UNKNOWN = 'unknown'
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    UNHEALTHY = 'unhealthy'
    UNAVAILABLE = 'unavailable'
    DISABLED = 'disabled'


class CircuitState(str, Enum):
    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'


@dataclass
class HealthRecord:
    state: str = HealthState.UNKNOWN.value
    configuration: str = 'unknown'
    transport: str = 'unknown'
    capability: str = 'unknown'
    latency_ms: float | None = None
    requests: int = 0
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    rate_limits: int = 0
    malformed: int = 0
    consecutive_failures: int = 0
    last_success_at: float | None = None
    last_failure_at: float | None = None
    recovered_at: float | None = None
    last_error_code: str | None = None
    latencies: deque = field(default_factory=lambda: deque(maxlen=128), repr=False)

    def public(self) -> dict:
        data = asdict(self)
        samples = list(self.latencies)
        data.pop('latencies', None)
        data['success_rate'] = round(self.successes / self.requests, 4) if self.requests else None
        if samples:
            ordered = sorted(samples)
            data['latency_p50_ms'] = ordered[int((len(ordered) - 1) * .50)]
            data['latency_p95_ms'] = ordered[int((len(ordered) - 1) * .95)]
        else:
            data['latency_p50_ms'] = data['latency_p95_ms'] = None
        return data


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    state: str = CircuitState.CLOSED.value
    failures: int = 0
    opened_at: float | None = None
    half_open_inflight: bool = False

    def allow(self, now: float) -> bool:
        if self.state == CircuitState.CLOSED.value:
            return True
        if self.state == CircuitState.OPEN.value:
            if self.opened_at is not None and now - self.opened_at >= self.recovery_seconds:
                self.state = CircuitState.HALF_OPEN.value
                self.half_open_inflight = False
            else:
                return False
        if self.state == CircuitState.HALF_OPEN.value:
            if self.half_open_inflight:
                return False
            self.half_open_inflight = True
            return True
        return False

    def success(self) -> str | None:
        previous = self.state
        self.state = CircuitState.CLOSED.value
        self.failures = 0
        self.opened_at = None
        self.half_open_inflight = False
        return self.state if previous != self.state else None

    def failure(self, now: float) -> str | None:
        previous = self.state
        self.half_open_inflight = False
        self.failures += 1
        if previous == CircuitState.HALF_OPEN.value or self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN.value
            self.opened_at = now
        return self.state if previous != self.state else None


class ModelObservability:
    """Thread-safe, bounded and privacy-safe model health/generation telemetry."""

    SAFE_FIELDS = {
        'generation_id', 'conversation_id', 'task_id', 'provider', 'model', 'capability',
        'sensitivity', 'routing_reason', 'started_at', 'completed_at', 'latency_ms',
        'result', 'retry_count', 'failover_count', 'attempted_targets', 'terminal_target',
        'error_code', 'input_tokens', 'output_tokens', 'total_tokens', 'cost',
    }

    def __init__(self, provider_ids, *, history_limit: int = 200):
        self._lock = threading.RLock()
        self.health = {provider_id: HealthRecord() for provider_id in provider_ids}
        self.breakers = {provider_id: CircuitBreaker() for provider_id in provider_ids}
        self.generations = deque(maxlen=max(10, int(history_limit)))
        self.counters = {
            'requests': 0, 'successes': 0, 'failures': 0, 'timeouts': 0,
            'retries': 0, 'failovers': 0, 'rate_limits': 0, 'malformed': 0,
            'capability_mismatch': 0, 'policy_blocked': 0, 'circuit_transitions': 0,
        }

    @staticmethod
    def generation_id() -> str:
        return f'gen_{uuid.uuid4().hex}'

    def configured(self, provider_id: str, configured: bool, disabled: bool = False):
        with self._lock:
            record = self.health[provider_id]
            record.configuration = 'disabled' if disabled else ('configured' if configured else 'not_configured')
            if disabled:
                record.state = HealthState.DISABLED.value
            elif not configured:
                record.state = HealthState.UNAVAILABLE.value

    def allowed(self, provider_id: str, now: float | None = None) -> bool:
        with self._lock:
            return self.breakers[provider_id].allow(time.time() if now is None else now)

    def success(self, provider_id: str, latency_ms: float, *, now: float | None = None):
        now = time.time() if now is None else now
        with self._lock:
            record = self.health[provider_id]
            was_bad = record.state in {HealthState.DEGRADED.value, HealthState.UNHEALTHY.value, HealthState.UNAVAILABLE.value}
            record.requests += 1; record.successes += 1; record.consecutive_failures = 0
            record.transport = 'available'; record.state = HealthState.HEALTHY.value
            record.latency_ms = latency_ms; record.latencies.append(latency_ms); record.last_success_at = now
            record.last_error_code = None
            if was_bad: record.recovered_at = now
            transition = self.breakers[provider_id].success()
            if transition: self.counters['circuit_transitions'] += 1
            self.counters['requests'] += 1; self.counters['successes'] += 1
            return transition

    def failure(self, provider_id: str, error_code: str, *, retryable: bool, now: float | None = None):
        now = time.time() if now is None else now
        with self._lock:
            record = self.health[provider_id]
            record.requests += 1; record.failures += 1; record.consecutive_failures += 1
            record.last_failure_at = now; record.last_error_code = error_code
            record.transport = 'unavailable' if error_code in {'connection_error','provider_unavailable','model_unavailable'} else 'degraded'
            record.state = HealthState.DEGRADED.value if retryable and record.consecutive_failures < 3 else HealthState.UNHEALTHY.value
            self.counters['requests'] += 1; self.counters['failures'] += 1
            if error_code == 'timeout': record.timeouts += 1; self.counters['timeouts'] += 1
            if error_code == 'rate_limited': record.rate_limits += 1; self.counters['rate_limits'] += 1
            if error_code == 'malformed_response': record.malformed += 1; self.counters['malformed'] += 1
            transition = self.breakers[provider_id].failure(now)
            if transition: self.counters['circuit_transitions'] += 1
            return transition

    def add_generation(self, row: dict):
        safe = {key: row.get(key) for key in self.SAFE_FIELDS if key in row}
        with self._lock:
            self.generations.append(safe)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'counters': dict(self.counters),
                'providers': {
                    key: {**record.public(), 'circuit': self.breakers[key].state}
                    for key, record in self.health.items()
                },
                'recent_generations': list(self.generations)[-25:],
            }
