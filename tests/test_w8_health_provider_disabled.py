from models.resilience import ModelObservability

def test_disabled_provider_configuration_is_visible_without_secret():
    obs=ModelObservability(['p']);obs.configured('p',True,disabled=True);row=obs.snapshot()['providers']['p'];assert row['configuration']=='disabled' and row['state']=='disabled'
