from models.resilience import ModelObservability

def test_retry_and_failover_metrics_start_at_zero():
    c=ModelObservability(['p']).snapshot()['counters'];assert c['retries']==0 and c['failovers']==0
