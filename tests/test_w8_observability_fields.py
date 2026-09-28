from models.resilience import ModelObservability


def test_generation_record_supports_required_safe_observability_fields():
    obs=ModelObservability(['p']);row={'generation_id':'g','conversation_id':'c','task_id':'t','provider':'p','model':'m','capability':'chat','routing_reason':'primary','started_at':1,'completed_at':2,'latency_ms':10,'result':'success','retry_count':1,'failover_count':0,'attempted_targets':['p'],'terminal_target':'p','error_code':None,'input_tokens':3,'output_tokens':4,'total_tokens':7,'cost':.01};obs.add_generation(row)
    saved=obs.snapshot()['recent_generations'][-1]
    for key in row:assert key in saved
