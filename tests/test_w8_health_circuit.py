from models.resilience import ModelObservability

def test_health_snapshot_always_includes_circuit_state():assert ModelObservability(['p']).snapshot()['providers']['p']['circuit']=='closed'
