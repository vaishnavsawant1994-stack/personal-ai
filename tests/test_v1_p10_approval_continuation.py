from __future__ import annotations

from types import SimpleNamespace

from core.p10_approval_continuation import install
from core.personal_ai_runtime import CanonicalTurnRuntime


class Continuity:
    def __init__(self): self.events={}
    def resume(self,*a,**k): return {'thread':{'id':'c1'}}
    def thread(self,cid): return {'id':cid,'closed_at':None}
    def set_active(self,*a): pass
    def conversation_history(self,*a,**k): return []
    def append(self,cid,*,device_id,kind,payload,event_id=None):
        if event_id in self.events:return {'duplicate':True}
        self.events[event_id]=(kind,payload);return {'duplicate':False}


class Executor:
    def __init__(self):
        self.approvals=SimpleNamespace(current_security_epoch=lambda:7);self.approve_calls=0;self.reject_calls=0
    def chat(self,text,**kwargs): return 'ordinary'
    def approve(self,*a,**k): self.approve_calls+=1;return 'lower'
    def reject(self,*a,**k): self.reject_calls+=1;return 'lower reject'


class Autonomy:
    def __init__(self):
        self.value={'id':'p1','state':'WAITING_APPROVAL','tasks':[{'id':'k1','status':'WAITING_APPROVAL','approval_ref':'a1','operation_id':'o1','requested_tool':'send','objective':'send governed message'}]}
        self.approved=0;self.denied=0;self.executed=[];self.estop=False
    def plan(self,*a,**k): return self.value
    def ready_tasks(self,*a,**k): return [x for x in self.value['tasks'] if x['status']=='READY']
    def approve_task(self,*a,**k):
        if self.estop: raise PermissionError('Emergency Stop active')
        self.approved+=1;self.value['tasks'][0]['status']='COMPLETED';self.value['tasks'][0]['result_ref']='o1'
        self.value['state']='COMPLETED' if all(x['status']=='COMPLETED' for x in self.value['tasks']) else 'RUNNING';return self.value
    def deny_task(self,*a,**k):
        self.denied+=1;self.value['tasks'][0]['status']='CANCELLED';self.value['state']='CANCELLED';return self.value
    def execute_task(self,plan_id,task_id,**kwargs):
        if self.estop: raise PermissionError('Emergency Stop blocks consequential work')
        self.executed.append(task_id);task=next(x for x in self.value['tasks'] if x['id']==task_id);task['status']='COMPLETED';task['result_ref']='op-'+task_id
        self.value['state']='COMPLETED' if all(x['status']=='COMPLETED' for x in self.value['tasks']) else 'RUNNING';return self.value


def bound_runtime(tmp_path, *, autonomy=None, db_name='turns.sqlite3'):
    install(CanonicalTurnRuntime);lower=Executor();r=CanonicalTurnRuntime(lower,Continuity(),tmp_path/db_name);a=autonomy or Autonomy();r.attach_autonomy(a)
    r._insert_started(request_id='r1',owner_id='owner',conversation_id='c1',device_id='d1',session_id='s1',surface='pwa',input_modality='text',privacy_level='normal',risk_level='low',user_text='do governed work')
    r._update('r1','needs_approval',approval_id='a1',p10_goal_id='g1',p10_plan_id='p1')
    return r,lower,a


def test_p10_approval_continues_orchestration_not_lower_turn_approval(tmp_path):
    r,lower,a=bound_runtime(tmp_path);answer=r.approve('a1',owner_id='owner',device_id='d1',session_id='s1')
    assert a.approved==1 and lower.approve_calls==0 and r.turn('r1')['status']=='completed'
    assert 'Completed the governed request' in answer
    assert len([k for k in r.continuity.events if k=='r1:assistant'])==1


def test_p10_denial_is_durable_and_does_not_call_lower_turn_reject(tmp_path):
    r,lower,a=bound_runtime(tmp_path);answer=r.reject('a1',owner_id='owner',device_id='d1',session_id='s1')
    assert a.denied==1 and lower.reject_calls==0 and r.turn('r1')['status']=='cancelled'
    assert r.turn('r1')['error_code']=='approval_denied' and 'cancelled' in answer.lower()


def test_p10_approval_requires_same_device_and_session(tmp_path):
    r,_,a=bound_runtime(tmp_path)
    for kwargs in ({'device_id':'other','session_id':'s1'},{'device_id':'d1','session_id':'other'},{'device_id':'d1'}):
        try:r.approve('a1',owner_id='owner',**kwargs)
        except PermissionError:pass
        else:raise AssertionError('stale or cross-authority approval must fail closed')
    assert a.approved==0


def test_duplicate_p10_approval_does_not_repeat_orchestration(tmp_path):
    r,_,a=bound_runtime(tmp_path);r.approve('a1',owner_id='owner',device_id='d1',session_id='s1')
    try:r.approve('a1',owner_id='owner',device_id='d1',session_id='s1')
    except PermissionError:pass
    else:raise AssertionError('consumed P10 approval must fail closed')
    assert a.approved==1


def test_estop_dominates_pending_p10_approval(tmp_path):
    a=Autonomy();r,lower,a=bound_runtime(tmp_path,autonomy=a);a.estop=True
    try:r.approve('a1',owner_id='owner',device_id='d1',session_id='s1')
    except PermissionError as exc: assert 'Emergency Stop' in str(exc)
    else: raise AssertionError('E-stop must block P10 approval continuation')
    assert a.approved==0 and lower.approve_calls==0 and r.turn('r1')['status']=='needs_approval'


def test_multitask_plan_continues_after_governed_approval(tmp_path):
    a=Autonomy();a.value['tasks'].extend([{'id':'k2','status':'READY','objective':'second','consequential':False},{'id':'k3','status':'READY','objective':'third','consequential':False}])
    r,lower,a=bound_runtime(tmp_path,autonomy=a);answer=r.approve('a1',owner_id='owner',device_id='d1',session_id='s1')
    assert a.approved==1 and a.executed==['k2','k3'] and lower.approve_calls==0
    assert r.turn('r1')['status']=='completed' and 'op-k2' in answer and 'op-k3' in answer


def test_install_is_idempotent_and_does_not_recursively_wrap(tmp_path):
    approve=CanonicalTurnRuntime.approve;reject=CanonicalTurnRuntime.reject
    install(CanonicalTurnRuntime);install(CanonicalTurnRuntime)
    assert CanonicalTurnRuntime.approve is approve and CanonicalTurnRuntime.reject is reject
    r,lower,_=bound_runtime(tmp_path);r.approve('a1',owner_id='owner',device_id='d1',session_id='s1')
    assert lower.approve_calls==0
