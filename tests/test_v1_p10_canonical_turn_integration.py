from __future__ import annotations

from types import SimpleNamespace

from core.personal_ai_runtime import CanonicalTurnRuntime, TurnReplayBlocked


class Continuity:
    def __init__(self): self.events={}; self.thread_id='c1'
    def resume(self,*a,**k): return {'thread':{'id':self.thread_id}}
    def thread(self,cid): return {'id':cid,'closed_at':None}
    def set_active(self,*a): pass
    def conversation_history(self,*a,**k): return []
    def append(self,cid,*,device_id,kind,payload,event_id=None):
        if event_id in self.events:return {'duplicate':True}
        self.events[event_id]=(kind,payload);return {'duplicate':False}


class Executor:
    def __init__(self): self.calls=0; self.approvals=SimpleNamespace(current_security_epoch=lambda:0)
    def chat(self,text,**kwargs): self.calls+=1; return 'ordinary:'+text


class Autonomy:
    def __init__(self): self.goals=[]; self.plans=[]; self.executed=[]
    def create_goal(self,text,**kwargs):
        goal={'id':'g1','description':text};self.goals.append((goal,kwargs));return goal
    def propose_plan_with_model(self,gid,**kwargs):
        plan={'id':'p1','goal_id':gid,'state':'READY','tasks':[{'id':'t1','status':'WAITING'}]};self.plans.append(plan);return plan
    def ready_tasks(self,pid,**kwargs):
        p=self.plans[-1];return [x for x in p['tasks'] if x['status']=='WAITING']
    def execute_task(self,pid,tid,**kwargs):
        self.executed.append((pid,tid,kwargs));p=self.plans[-1];p['tasks'][0]['status']='COMPLETED';p['state']='COMPLETED';return p
    def plan(self,pid,**kwargs): return self.plans[-1]


def runtime(tmp_path):
    executor=Executor(); r=CanonicalTurnRuntime(executor,Continuity(),tmp_path/'turns.sqlite3');return r,executor


def test_simple_chat_does_not_enter_p10(tmp_path):
    r,e=runtime(tmp_path);a=Autonomy();r.attach_autonomy(a)
    assert r.chat('What is Python?',request_id='r1')=='ordinary:What is Python?'
    assert e.calls==1 and not a.goals


def test_deterministic_multistep_turn_enters_existing_p10_and_not_ordinary_executor(tmp_path):
    r,e=runtime(tmp_path);a=Autonomy();r.attach_autonomy(a)
    answer=r.chat('Research these companies, then verify them and prepare a report.',request_id='r2')
    assert 'Orchestration completed' in answer
    assert e.calls==0
    assert len(a.goals)==1 and len(a.plans)==1 and len(a.executed)==1
    assert a.goals[0][1]['request_id']=='r2'


def test_completed_replay_does_not_create_second_p10_goal_or_execution(tmp_path):
    r,e=runtime(tmp_path);a=Autonomy();r.attach_autonomy(a);text='Research these companies, then verify them and prepare a report.'
    first=r.chat(text,request_id='same');second=r.chat(text,request_id='same')
    assert first==second
    assert len(a.goals)==1 and len(a.executed)==1 and e.calls==0
    assert len(r.continuity.events)==2


def test_conflicting_replay_fails_closed(tmp_path):
    r,e=runtime(tmp_path);r.chat('What is Python?',request_id='same')
    try:r.chat('Different payload',request_id='same')
    except PermissionError:pass
    else:raise AssertionError('conflicting request replay must fail closed')
    assert e.calls==1


def test_request_id_is_bound_to_device_and_conversation(tmp_path):
    r,e=runtime(tmp_path);r.chat('What is Python?',request_id='r',device_id='d1',conversation_id='c1')
    try:r.chat('What is Python?',request_id='r',device_id='d2',conversation_id='c1')
    except PermissionError:pass
    else:raise AssertionError('cross-device replay must fail closed')


def test_stage7_repeated_cancel_is_idempotent(tmp_path):
    r,e=runtime(tmp_path)
    r._claim_started(request_id='cancel-me',owner_id='owner',conversation_id='c1',device_id='d1',session_id=None,surface='device',input_modality='text',privacy_level='normal',risk_level='low',user_text='work')
    first=r.cancel_turn('cancel-me',device_id='d1')
    second=r.cancel_turn('cancel-me',device_id='d1')
    assert first['status']=='cancelled' and second['status']=='cancelled'
    assert r.turn('cancel-me')['error_code']=='cancelled'


def test_stage7_repeated_emergency_stop_cancellation_is_idempotent(tmp_path):
    r,e=runtime(tmp_path)
    r._claim_started(request_id='active',owner_id='owner',conversation_id='c1',device_id='d1',session_id=None,surface='device',input_modality='text',privacy_level='normal',risk_level='low',user_text='work')
    assert r.cancel_active_turns(reason='emergency_stop')==1
    assert r.cancel_active_turns(reason='emergency_stop')==0
    assert r.turn('active')['status']=='cancelled'
    assert r.turn('active')['error_code']=='emergency_stop'


def test_stage7_late_completion_cannot_resurrect_cancelled_turn(tmp_path):
    r,e=runtime(tmp_path)
    r._claim_started(request_id='late',owner_id='owner',conversation_id='c1',device_id='d1',session_id=None,surface='device',input_modality='text',privacy_level='normal',risk_level='low',user_text='work')
    r.cancel_active_turns(reason='emergency_stop')
    assert r._update('late','completed',assistant_text='late result') is False
    turn=r.turn('late')
    assert turn['status']=='cancelled'
    assert turn['assistant_text'] is None
    assert turn['error_code']=='emergency_stop'
