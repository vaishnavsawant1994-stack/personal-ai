from concurrent.futures import ThreadPoolExecutor
from models.resilience import CircuitState,ModelObservability


def test_concurrent_failures_open_one_consistent_circuit():
    obs=ModelObservability(['p']);obs.breakers['p'].failure_threshold=3
    with ThreadPoolExecutor(max_workers=12) as pool:list(pool.map(lambda i:obs.failure('p','provider_unavailable',retryable=True),range(24)))
    snap=obs.snapshot();assert snap['providers']['p']['circuit']==CircuitState.OPEN.value
    assert snap['counters']['requests']==24 and snap['counters']['failures']==24


def test_open_circuit_blocks_request_storm_until_recovery_window():
    obs=ModelObservability(['p']);b=obs.breakers['p'];b.failure_threshold=1;b.recovery_seconds=100
    obs.failure('p','provider_unavailable',retryable=True,now=1)
    assert all(obs.allowed('p',now=t) is False for t in range(2,50))
