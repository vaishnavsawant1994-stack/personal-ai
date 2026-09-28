from models.resilience import ModelObservability

def test_provider_identity_supports_local_external_routing_aggregation():
    obs=ModelObservability(['self_hosted','openai']);obs.add_generation({'generation_id':'a','provider':'self_hosted','result':'success'});obs.add_generation({'generation_id':'b','provider':'openai','result':'success'});rows=obs.snapshot()['recent_generations'];assert [r['provider'] for r in rows]==['self_hosted','openai']
