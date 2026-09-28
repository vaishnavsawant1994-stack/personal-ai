from models.resilience import ModelObservability

def test_malformed_response_is_visible_and_not_marked_healthy():
    obs=ModelObservability(['p']);obs.failure('p','malformed_response',retryable=False,now=1);row=obs.snapshot()['providers']['p'];assert row['malformed']==1 and row['state']=='unhealthy'
