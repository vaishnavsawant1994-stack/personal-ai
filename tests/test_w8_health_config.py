from models.resilience import ModelObservability

def test_configuration_health_is_separate_from_runtime_health():
    obs=ModelObservability(['p']);obs.configured('p',True);row=obs.snapshot()['providers']['p'];assert row['configuration']=='configured' and row['state']=='unknown'
