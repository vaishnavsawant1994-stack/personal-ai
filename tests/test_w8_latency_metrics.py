from models.resilience import ModelObservability

def test_latency_distribution_is_reported_not_only_average():
    obs=ModelObservability(['p']);[obs.success('p',v) for v in (1,2,3,100)]
    row=obs.snapshot()['providers']['p'];assert 'latency_p50_ms' in row and 'latency_p95_ms' in row
