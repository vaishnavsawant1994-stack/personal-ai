from models.resilience import ModelObservability


def test_half_open_allows_only_one_probe_at_a_time():
    obs=ModelObservability(['p']);b=obs.breakers['p'];b.failure_threshold=1;b.recovery_seconds=1
    obs.failure('p','provider_unavailable',retryable=True,now=1)
    assert obs.allowed('p',now=2) is True
    assert obs.allowed('p',now=2) is False
