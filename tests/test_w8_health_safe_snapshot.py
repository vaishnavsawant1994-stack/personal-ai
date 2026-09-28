from models.resilience import ModelObservability

def test_snapshot_returns_plain_safe_data():
    snap=ModelObservability(['p']).snapshot();assert isinstance(snap,dict) and isinstance(snap['providers']['p'],dict) and isinstance(snap['recent_generations'],list)
