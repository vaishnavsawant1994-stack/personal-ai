from models.resilience import ModelObservability

def test_aggregate_request_counter_matches_health_updates():
    obs=ModelObservability(['a','b']);obs.success('a',1);obs.failure('b','timeout',retryable=True);assert obs.snapshot()['counters']['requests']==2
