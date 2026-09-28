from models.resilience import ModelObservability

def test_last_latency_is_recorded_on_success():
    obs=ModelObservability(['p']);obs.success('p',12.5);assert obs.snapshot()['providers']['p']['latency_ms']==12.5
