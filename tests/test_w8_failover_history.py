from models.resilience import ModelObservability

def test_attempted_targets_are_safe_ids_not_endpoints():
    obs=ModelObservability(['p']);obs.add_generation({'generation_id':'g','attempted_targets':['self_hosted','openai'],'result':'failed'});assert obs.snapshot()['recent_generations'][-1]['attempted_targets']==['self_hosted','openai']
