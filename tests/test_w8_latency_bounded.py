from models.resilience import ModelObservability

def test_latency_samples_are_bounded():
    obs=ModelObservability(['p'])
    for i in range(300):obs.success('p',i)
    assert len(obs.health['p'].latencies)==128
