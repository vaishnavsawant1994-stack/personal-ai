from models.resilience import ModelObservability

def test_provider_recovers_after_success():
    obs=ModelObservability(['p'])
    for i in range(3):obs.failure('p','provider_unavailable',retryable=True,now=i)
    obs.success('p',4,now=100)
    row=obs.snapshot()['providers']['p']
    assert row['state']=='healthy' and row['circuit']=='closed' and row['recovered_at']==100
