from models.resilience import ModelObservability

def test_disabled_health_is_explicit():
    obs=ModelObservability(['p']);obs.configured('p',True,disabled=True);assert obs.snapshot()['providers']['p']['configuration']=='disabled'
