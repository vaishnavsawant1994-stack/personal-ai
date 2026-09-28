from models.resilience import ModelObservability

def test_open_circuit_does_not_oscillate_without_recovery_window():
    obs=ModelObservability(['p']);b=obs.breakers['p'];b.failure_threshold=1;b.recovery_seconds=10;obs.failure('p','timeout',retryable=True,now=1)
    assert [obs.allowed('p',now=t) for t in (2,3,4,5)]==[False]*4
