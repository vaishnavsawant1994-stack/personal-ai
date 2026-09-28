from concurrent.futures import ThreadPoolExecutor

from models.resilience import CircuitState, HealthState, ModelObservability


def test_health_success_and_latency_distribution():
    obs = ModelObservability(['local'])
    obs.configured('local', True)
    obs.success('local', 10, now=1)
    obs.success('local', 30, now=2)
    status = obs.snapshot()['providers']['local']
    assert status['state'] == HealthState.HEALTHY.value
    assert status['success_rate'] == 1.0
    assert status['latency_p50_ms'] == 10
    assert status['latency_p95_ms'] == 10


def test_circuit_opens_half_opens_and_recovers():
    obs = ModelObservability(['p'])
    breaker = obs.breakers['p']; breaker.recovery_seconds = 5
    for now in (1, 2, 3): obs.failure('p', 'provider_unavailable', retryable=True, now=now)
    assert breaker.state == CircuitState.OPEN.value
    assert obs.allowed('p', now=4) is False
    assert obs.allowed('p', now=8) is True
    assert breaker.state == CircuitState.HALF_OPEN.value
    assert obs.allowed('p', now=8) is False
    obs.success('p', 5, now=9)
    assert breaker.state == CircuitState.CLOSED.value


def test_half_open_failure_reopens():
    obs = ModelObservability(['p']); breaker = obs.breakers['p']; breaker.failure_threshold=1; breaker.recovery_seconds=1
    obs.failure('p','timeout',retryable=True,now=1)
    assert obs.allowed('p',now=2) is True
    obs.failure('p','timeout',retryable=True,now=2)
    assert breaker.state == CircuitState.OPEN.value


def test_generation_telemetry_is_allowlisted_and_redacted():
    obs = ModelObservability(['p'])
    obs.add_generation({'generation_id':'gen_1','provider':'p','result':'success','prompt':'private','api_key':'secret','response':'private answer','authorization':'Bearer secret'})
    text = repr(obs.snapshot())
    assert 'gen_1' in text
    assert 'private' not in text
    assert 'secret' not in text
    assert 'authorization' not in text


def test_failure_metrics_are_classified():
    obs=ModelObservability(['p'])
    obs.failure('p','timeout',retryable=True,now=1)
    obs.failure('p','rate_limited',retryable=True,now=2)
    obs.failure('p','malformed_response',retryable=False,now=3)
    counters=obs.snapshot()['counters']
    assert counters['requests']==3 and counters['failures']==3
    assert counters['timeouts']==1 and counters['rate_limits']==1 and counters['malformed']==1


def test_concurrent_health_updates_are_consistent():
    obs=ModelObservability(['p'])
    def work(i): obs.success('p',float(i+1))
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(work,range(50)))
    snapshot=obs.snapshot()
    assert snapshot['counters']['requests']==50
    assert snapshot['counters']['successes']==50
    assert snapshot['providers']['p']['requests']==50


def test_disabled_provider_state_is_explicit():
    obs=ModelObservability(['p']); obs.configured('p',False,disabled=True)
    assert obs.snapshot()['providers']['p']['state']==HealthState.DISABLED.value
