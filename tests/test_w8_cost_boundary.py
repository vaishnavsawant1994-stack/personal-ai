from models.resilience import ModelObservability


def test_cost_is_optional_not_fabricated():
    obs=ModelObservability(['p']);obs.add_generation({'generation_id':'g','provider':'p','result':'success'})
    assert 'cost' not in obs.snapshot()['recent_generations'][-1]
