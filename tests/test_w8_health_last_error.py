from models.resilience import ModelObservability

def test_success_clears_last_error_code():
    obs=ModelObservability(['p']);obs.failure('p','timeout',retryable=True);obs.success('p',1);assert obs.snapshot()['providers']['p']['last_error_code'] is None
