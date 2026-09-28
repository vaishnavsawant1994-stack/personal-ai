from models.resilience import ModelObservability


def test_health_dimensions_are_distinct():
    obs=ModelObservability(['p']);obs.configured('p',True);row=obs.snapshot()['providers']['p']
    assert row['configuration']=='configured'
    assert row['transport']=='unknown'
    assert row['capability']=='unknown'
