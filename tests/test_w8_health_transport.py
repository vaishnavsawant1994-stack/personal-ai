from models.resilience import ModelObservability

def test_transport_health_updates_from_request_outcome():
    obs=ModelObservability(['p']);obs.failure('p','provider_unavailable',retryable=True);assert obs.snapshot()['providers']['p']['transport']=='unavailable';obs.success('p',1);assert obs.snapshot()['providers']['p']['transport']=='available'
