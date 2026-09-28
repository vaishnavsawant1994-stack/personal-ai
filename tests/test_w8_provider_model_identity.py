from models.resilience import ModelObservability

def test_generation_identity_records_selected_provider_and_model_only_when_known():
    obs=ModelObservability(['p']);obs.add_generation({'generation_id':'g','provider':'p','model':'m','result':'success'});row=obs.snapshot()['recent_generations'][-1];assert row['provider']=='p' and row['model']=='m'
