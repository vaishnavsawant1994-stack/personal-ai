from models.resilience import ModelObservability

def test_not_configured_provider_is_unavailable_not_healthy():
    obs=ModelObservability(['p']);obs.configured('p',False);assert obs.snapshot()['providers']['p']['state']=='unavailable'
