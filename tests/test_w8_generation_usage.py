from models.resilience import ModelObservability

def test_usage_fields_are_optional_and_supported_when_reliable():
    obs=ModelObservability(['p']);obs.add_generation({'generation_id':'g','input_tokens':1,'output_tokens':2,'total_tokens':3,'result':'success'});row=obs.snapshot()['recent_generations'][-1];assert row['total_tokens']==3
