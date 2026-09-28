from models.resilience import ModelObservability

def test_recent_generation_output_is_capped_for_owner_diagnostics():
    obs=ModelObservability(['p'],history_limit=100)
    for i in range(80):obs.add_generation({'generation_id':str(i),'provider':'p','result':'success'})
    assert len(obs.snapshot()['recent_generations'])==25
