from models.resilience import ModelObservability

def test_health_tracks_last_success_failure_and_consecutive_failures():
    obs=ModelObservability(['p']);obs.failure('p','timeout',retryable=True,now=1);obs.failure('p','timeout',retryable=True,now=2)
    row=obs.snapshot()['providers']['p'];assert row['last_failure_at']==2 and row['consecutive_failures']==2
    obs.success('p',7,now=3);row=obs.snapshot()['providers']['p'];assert row['last_success_at']==3 and row['consecutive_failures']==0
