from models.resilience import ModelObservability

def test_disabled_provider_is_never_considered_healthy():
    obs=ModelObservability(['p']);obs.configured('p',True,disabled=True)
    assert obs.snapshot()['providers']['p']['state']=='disabled'
