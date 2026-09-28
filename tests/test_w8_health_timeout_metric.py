from models.resilience import ModelObservability

def test_timeout_counter_is_per_provider_and_aggregate():
    obs=ModelObservability(['p']);obs.failure('p','timeout',retryable=True);snap=obs.snapshot();assert snap['providers']['p']['timeouts']==1 and snap['counters']['timeouts']==1
