from models.resilience import ModelObservability


def test_unknown_health_does_not_equal_healthy():
    status=ModelObservability(['p']).snapshot()['providers']['p']
    assert status['state']=='unknown' and status['state']!='healthy'
