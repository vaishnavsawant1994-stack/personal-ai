from models.resilience import ModelObservability

def test_failure_counter_increments_for_safe_classified_failure():
    obs=ModelObservability(['p']);obs.failure('p','authentication_error',retryable=False);assert obs.snapshot()['counters']['failures']==1
