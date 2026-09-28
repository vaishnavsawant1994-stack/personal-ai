from models.resilience import ModelObservability

def test_configured_state_remains_unknown_until_runtime_evidence():
    obs=ModelObservability(['p']);obs.configured('p',True);assert obs.snapshot()['providers']['p']['state']=='unknown'
