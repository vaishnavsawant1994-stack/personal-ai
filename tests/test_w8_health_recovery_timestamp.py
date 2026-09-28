from models.resilience import ModelObservability

def test_recovery_timestamp_records_recovered_provider():
    obs=ModelObservability(['p']);obs.failure('p','provider_unavailable',retryable=True,now=1);obs.success('p',2,now=2);assert obs.snapshot()['providers']['p']['recovered_at']==2
