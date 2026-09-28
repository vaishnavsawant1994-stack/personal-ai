from models.resilience import ModelObservability

def test_generation_records_support_start_and_completion_timestamps():
    obs=ModelObservability(['p']);obs.add_generation({'generation_id':'g','started_at':1,'completed_at':2,'result':'success'});row=obs.snapshot()['recent_generations'][-1];assert row['started_at']==1 and row['completed_at']==2
