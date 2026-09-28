from models.resilience import ModelObservability

def test_health_retains_safe_error_code_not_error_message():
    obs=ModelObservability(['p']);obs.failure('p','timeout',retryable=True);row=obs.snapshot()['providers']['p'];assert row['last_error_code']=='timeout'
