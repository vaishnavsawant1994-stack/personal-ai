from models.resilience import ModelObservability

def test_success_failure_rates_are_truthful():
    obs=ModelObservability(['p']);obs.success('p',1);obs.failure('p','timeout',retryable=True);row=obs.snapshot()['providers']['p'];assert row['requests']==2 and row['successes']==1 and row['failures']==1 and row['success_rate']==.5
