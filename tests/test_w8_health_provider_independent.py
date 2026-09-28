from models.resilience import ModelObservability

def test_one_provider_circuit_does_not_open_another():
    obs=ModelObservability(['a','b']);obs.breakers['a'].failure_threshold=1;obs.failure('a','timeout',retryable=True,now=1)
    snap=obs.snapshot()['providers'];assert snap['a']['circuit']=='open' and snap['b']['circuit']=='closed'
