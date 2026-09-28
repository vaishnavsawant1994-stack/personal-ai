from models.resilience import ModelObservability

def test_health_record_tracks_request_outcomes_beyond_transport():
    row=ModelObservability(['p']).snapshot()['providers']['p'];assert {'requests','successes','failures','timeouts','rate_limits','malformed','consecutive_failures'}.issubset(row)
