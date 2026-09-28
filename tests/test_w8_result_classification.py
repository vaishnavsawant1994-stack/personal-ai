from models.resilience import ModelObservability

def test_generation_result_classification_is_safe_and_explicit():
    obs=ModelObservability(['p']);obs.add_generation({'generation_id':'g','provider':'p','result':'failed','error_code':'timeout'});row=obs.snapshot()['recent_generations'][-1]
    assert row['result']=='failed' and row['error_code']=='timeout'
