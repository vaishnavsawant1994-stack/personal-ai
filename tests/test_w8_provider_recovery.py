from models.resilience import ModelObservability

def test_recovery_timestamp_only_follows_bad_health():
    obs=ModelObservability(['p']);obs.success('p',1,now=1);assert obs.snapshot()['providers']['p']['recovered_at'] is None
    obs.failure('p','timeout',retryable=True,now=2);obs.success('p',1,now=3);assert obs.snapshot()['providers']['p']['recovered_at']==3
