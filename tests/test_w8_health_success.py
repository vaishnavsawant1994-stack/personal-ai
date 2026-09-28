from models.resilience import ModelObservability

def test_success_sets_transport_available_and_clears_error():
    obs=ModelObservability(['p']);obs.failure('p','timeout',retryable=True);obs.success('p',3);row=obs.snapshot()['providers']['p'];assert row['transport']=='available' and row['last_error_code'] is None
