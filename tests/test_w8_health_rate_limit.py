from models.resilience import ModelObservability

def test_rate_limit_is_visible_as_degraded_health():
    obs=ModelObservability(['p']);obs.failure('p','rate_limited',retryable=True,now=1);row=obs.snapshot()['providers']['p'];assert row['rate_limits']==1 and row['state']=='degraded'
