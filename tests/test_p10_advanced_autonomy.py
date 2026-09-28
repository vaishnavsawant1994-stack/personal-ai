import pytest
from future_intelligence.autonomy import AdvancedAutonomy,PlanState

class Decision:
    allowed=True; reason='ok'
class Gate:
    def decision(self,_): return Decision()

def make(tmp_path,stop=lambda:False): return AdvancedAutonomy(gate=Gate(),path=tmp_path/'p10.sqlite3',emergency_stop_provider=stop)

def test_goal_and_bounded_plan(tmp_path):
    a=make(tmp_path); g=a.create_goal('weekly review',allowed_capabilities=['read','analyze'])
    p=a.create_plan(g['id'],[{'id':'read','objective':'read','required_capabilities':['read']},{'id':'analyze','objective':'analyze','dependencies':['read'],'required_capabilities':['analyze']}])
    assert [x['id'] for x in a.ready_tasks(p['id'])]==['read']
    p=a.mark_task(p['id'],'read','completed'); assert [x['id'] for x in a.ready_tasks(p['id'])]==['analyze']

def test_child_cannot_expand_authority(tmp_path):
    a=make(tmp_path); g=a.create_goal('x',allowed_capabilities=['read'],prohibited_actions=['delete'])
    with pytest.raises(PermissionError): a.create_plan(g['id'],[{'id':'x','required_capabilities':['write']}])
    with pytest.raises(PermissionError): a.create_plan(g['id'],[{'id':'x','action':'delete'}])

def test_cycle_duplicate_and_bounds_rejected(tmp_path):
    a=make(tmp_path); g=a.create_goal('x')
    with pytest.raises(ValueError): a.create_plan(g['id'],[{'id':'a','dependencies':['b']},{'id':'b','dependencies':['a']}])
    with pytest.raises(ValueError): a.create_plan(g['id'],[{'id':'a'},{'id':'a'}])
    with pytest.raises(ValueError): a.create_plan(g['id'],[{'id':str(i)} for i in range(51)])

def test_verification_failure_never_claims_success(tmp_path):
    a=make(tmp_path); g=a.create_goal('x'); p=a.create_plan(g['id'],[{'id':'x','verification_required':True,'consequential':True}])
    p=a.mark_task(p['id'],'x','completed',verified=False); assert p['state']==PlanState.UNCERTAIN.value and p['tasks'][0]['status']=='UNCERTAIN'

def test_emergency_stop_blocks_consequential_but_not_readonly(tmp_path):
    a=make(tmp_path,lambda:True); g=a.create_goal('x'); p=a.create_plan(g['id'],[{'id':'read'},{'id':'write','consequential':True}])
    a.mark_task(p['id'],'read','completed')
    with pytest.raises(PermissionError): a.mark_task(p['id'],'write','completed')

def test_cancel_prevents_queued_work(tmp_path):
    a=make(tmp_path); g=a.create_goal('x'); p=a.create_plan(g['id'],[{'id':'a'},{'id':'b','dependencies':['a'],'consequential':True}]); p=a.cancel(p['id']); assert p['state']=='CANCELLED' and all(x['status']=='CANCELLED' for x in p['tasks'])

def test_restart_marks_active_work_uncertain(tmp_path):
    a=make(tmp_path); g=a.create_goal('x'); p=a.create_plan(g['id'],[{'id':'a'}]); a.mark_task(p['id'],'a','running'); b=make(tmp_path); assert b.plan(p['id'])['state']=='UNCERTAIN'

def test_replanning_bounded(tmp_path):
    a=make(tmp_path); g=a.create_goal('x'); p=a.create_plan(g['id'],[{'id':'a'}])
    for i in range(5): p=a.replan(p['id'],[{'id':f'a{i}'}])
    with pytest.raises(RuntimeError): a.replan(p['id'],[{'id':'last'}])

def test_proactive_is_suggestion_not_action(tmp_path):
    a=make(tmp_path); g=a.create_goal('x'); s=a.proactive_suggestion(g['id'],'automate this',consequential=True); assert s['kind']=='SUGGESTION' and s['action_authority'] is False

def test_context_is_bounded_and_separated(tmp_path):
    a=make(tmp_path); g=a.create_goal('x'); c=a.context_projection(g['id'],memory_items=range(100),knowledge_items=['k']*100,world_items=['w']*100,limit=3); assert len(c['memory'])==len(c['knowledge'])==len(c['world'])==3 and c['authority'] is False

def test_lessons_cannot_mutate_policy_or_code(tmp_path):
    a=make(tmp_path); g=a.create_goal('x'); x=a.record_lesson(g['id'],'verification_failed','tool lied'); assert x['evidence']['policy_mutation'] is False and x['evidence']['source_code_mutation'] is False

def test_agent_is_worker_only(tmp_path):
    a=make(tmp_path); x=a.create_agent('research','research',['web']); assert x['authority']=='worker_only' and x['enabled'] is False
