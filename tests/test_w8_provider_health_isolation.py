from models.resilience import ModelObservability

def test_provider_health_is_independent():
    obs=ModelObservability(['a','b']);obs.failure('a','timeout',retryable=True,now=1);obs.success('b',2,now=1)
    rows=obs.snapshot()['providers'];assert rows['a']['state']=='degraded' and rows['b']['state']=='healthy'
