from models.resilience import ModelObservability

def test_open_circuit_fails_closed_before_recovery_period():
    obs=ModelObservability(['p']);b=obs.breakers['p'];b.failure_threshold=1;b.recovery_seconds=30;obs.failure('p','timeout',retryable=True,now=100);assert obs.allowed('p',now=129) is False
