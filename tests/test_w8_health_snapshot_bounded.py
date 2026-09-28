from models.resilience import HealthRecord

def test_health_latency_window_is_bounded():assert HealthRecord().latencies.maxlen==128
