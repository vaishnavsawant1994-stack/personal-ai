from models.resilience import ModelObservability

def test_failure_then_success_resets_consecutive_failure_count():
    obs=ModelObservability(['p']);obs.failure('p','timeout',retryable=True);obs.success('p',1);assert obs.snapshot()['providers']['p']['consecutive_failures']==0
