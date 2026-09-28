from models.resilience import ModelObservability

def test_success_closes_half_open_circuit():
    obs=ModelObservability(['p']);b=obs.breakers['p'];b.failure_threshold=1;b.recovery_seconds=1;obs.failure('p','timeout',retryable=True,now=1);assert obs.allowed('p',now=2);obs.success('p',1,now=2);assert obs.snapshot()['providers']['p']['circuit']=='closed'
