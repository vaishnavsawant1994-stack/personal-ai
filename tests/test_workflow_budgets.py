from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
import pytest

from automation.budget import WorkflowBudgetError, WorkflowBudgetManager, WorkflowRecoveryRequired, normalize_policy
from automation.engine import AutomationEngine
from tools.registry import ToolRegistry
from desktop.operator_transactions import OperatorTransactionStore
from recovery.operator_recovery import VerificationRecord

class Memory:
    def audit(self,*a,**k): return None
class ModelStub: pass
class ToolRegistryStub:
    def __init__(self): self._tools=[]; self.emergency_stop=False
    def register(self,tool): self._tools.append(tool)
    def all(self): return list(self._tools)
    def set_emergency_stop(self,enabled): self.emergency_stop=bool(enabled); return self.emergency_stop
class Executor:
    def __init__(self): self.memory=Memory(); self.models=ModelStub(); self.tools=ToolRegistryStub(); self.calls=0
    def chat(self,prompt,cancel_event=None,**kwargs):
        self.calls+=1
        if cancel_event is not None and cancel_event.is_set():
            from agent.executor import ExecutionCancelled
            raise ExecutionCancelled('cancelled')
        return f'ok:{prompt}'
    def approve(self,*a,**k): return 'approved'
    def reject(self,*a,**k): return 'rejected'

def workflow(engine,*,policy=None,steps=None):
    return engine.create_workflow('bounded',{'type':'manual'},steps or [{'kind':'set','key':'x','value':1}],policy=policy)

def test_additive_migration_preserves_legacy_rows(tmp_path):
    path=tmp_path/'a.sqlite3'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE workflows(id TEXT PRIMARY KEY,title TEXT,trigger_json TEXT,steps_json TEXT,enabled INTEGER,paused INTEGER,next_run_at TEXT,interval_seconds INTEGER,created_at TEXT,updated_at TEXT,last_run_at TEXT)')
        con.execute('CREATE TABLE workflow_runs(id TEXT PRIMARY KEY,workflow_id TEXT,status TEXT,trigger_json TEXT,context_json TEXT,current_step INTEGER,completed_steps_json TEXT,result_json TEXT,error TEXT,pending_approval_id TEXT,started_at TEXT,updated_at TEXT,completed_at TEXT)')
        con.execute("INSERT INTO workflows VALUES('w','legacy','{\"type\":\"manual\"}','[{\"kind\":\"set\",\"key\":\"x\",\"value\":1,\"position\":0,\"retries\":0,\"timeout_seconds\":10}]',1,0,NULL,NULL,'2026-01-01','2026-01-01',NULL)")
        con.execute("INSERT INTO workflow_runs VALUES('r','w','running','{}','{}',0,'[]',NULL,NULL,NULL,'2026-01-01','2026-01-01',NULL)")
    e=AutomationEngine(path,executor=Executor())
    assert e.workflow('w')['policy']['max_steps']==50 and e._run('r')['status']=='recovery_required'
    assert e.budget_status('r')['reserved_concurrency'] is False

def test_default_policy_compatibility(tmp_path):
    e=AutomationEngine(tmp_path/'a.sqlite3',executor=Executor()); w=workflow(e); r=e.run_workflow(w,background=False)
    assert e._run(r)['status']=='completed' and e.budget_status(r)['policy']['max_steps']==50

def test_invalid_and_excessive_policy_rejected():
    with pytest.raises(ValueError): normalize_policy({'max_concurrent_runs':0})
    with pytest.raises(ValueError): normalize_policy({'max_model_calls':10001})

def test_step_limit(tmp_path):
    e=AutomationEngine(tmp_path/'a.sqlite3',executor=Executor())
    with pytest.raises(ValueError): workflow(e,policy={'max_steps':1},steps=[{'kind':'set','key':'a','value':1},{'kind':'set','key':'b','value':2}])

def test_retry_limit(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3'); m.reserve_run('r','w',normalize_policy({'max_retries':1})); m.increment_retry('r')
    with pytest.raises(WorkflowBudgetError): m.increment_retry('r')

def test_runtime_deadline(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3'); m.reserve_run('r','w',normalize_policy({'max_runtime_seconds':1})); time.sleep(1.02)
    with pytest.raises(WorkflowBudgetError,match='runtime'): m.check('r')

def test_model_and_tool_call_limits(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3'); m.reserve_run('r','w',normalize_policy({'max_model_calls':1,'max_tool_calls':1}))
    with m.enter('r',0,0):
        d=m.begin_dispatch('model','p:a');m.finish_dispatch(d); t=m.begin_dispatch('tool','x:a');m.finish_dispatch(t)
        with pytest.raises(WorkflowBudgetError): m.begin_dispatch('model','p:b')
        with pytest.raises(WorkflowBudgetError): m.begin_dispatch('tool','x:b')

def test_confirmed_token_cost_and_gemini_usage(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3');m.reserve_run('r','w',normalize_policy({}))
    with m.enter('r',0,0): m.record_provider_usage({'usageMetadata':{'promptTokenCount':5,'candidatesTokenCount':2,'totalTokenCount':7}})
    s=m.status('r'); assert s['confirmed_usage'] and s['consumption']['total_tokens']==7 and s['consumption']['confirmed_cost']==0

def test_unknown_usage_is_not_claimed_confirmed(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3');m.reserve_run('r','w',normalize_policy({}));s=m.status('r')
    assert s['usage_state']=='unavailable' and s['confirmed_usage'] is False

def test_hard_cost_budget_without_preflight_fails_closed(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3');m.reserve_run('r','w',normalize_policy({'max_cost':1.0}))
    with pytest.raises(WorkflowBudgetError,match='unavailable'): m.check('r')

def test_atomic_concurrency_race(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3');p=normalize_policy({'max_concurrent_runs':1});barrier=threading.Barrier(2);out=[]
    def go(i):
        barrier.wait()
        try:m.reserve_run(str(i),'w',p);out.append('ok')
        except WorkflowBudgetError:out.append('blocked')
    a=threading.Thread(target=go,args=(1,));b=threading.Thread(target=go,args=(2,));a.start();b.start();a.join();b.join();assert sorted(out)==['blocked','ok']

def test_multiple_manager_instances_share_slot(tmp_path):
    path=tmp_path/'b.sqlite3';a=WorkflowBudgetManager(path);b=WorkflowBudgetManager(path);p=normalize_policy({'max_concurrent_runs':1});a.reserve_run('a','w',p)
    with pytest.raises(WorkflowBudgetError): b.reserve_run('b','w',p)

def test_restart_active_reservation_requires_review(tmp_path):
    path=tmp_path/'a.sqlite3';e=AutomationEngine(path,executor=Executor());w=workflow(e);r=e.run_workflow(w,background=False)
    with sqlite3.connect(path) as con: con.execute("UPDATE workflow_runs SET status='running' WHERE id=?",(r,))
    with e.budgets._con() as con: con.execute("UPDATE workflow_budget_runs SET reserved_concurrency=1,released_at=NULL WHERE run_id=?",(r,))
    reopened=AutomationEngine(path,executor=Executor());assert reopened._run(r)['status']=='recovery_required';assert not reopened.budget_status(r)['reserved_concurrency']

def test_approval_wait_retains_slot(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3');m.reserve_run('r','w',normalize_policy({}));m.mark_approval_wait('r');s=m.status('r');assert s['reserved_concurrency'] and s['consumption']['approval_waits']==1

def test_wrong_session_approval_rejected(tmp_path):
    e=AutomationEngine(tmp_path/'a.sqlite3',executor=Executor());w=workflow(e);r=e.run_workflow(w,background=False,owner_id='owner',device_id='d1',session_id='s1')
    with sqlite3.connect(e.path) as con: con.execute("UPDATE workflow_runs SET status='waiting_approval',pending_approval_id='a' WHERE id=?",(r,))
    with pytest.raises(PermissionError): e.approve_run(r,'a',owner_id='owner',device_id='d1',session_id='s2')

def test_duplicate_resume_is_blocked(tmp_path):
    e=AutomationEngine(tmp_path/'a.sqlite3',executor=Executor());w=workflow(e);r=e.run_workflow(w,background=False)
    with sqlite3.connect(e.path) as con: con.execute("UPDATE workflow_runs SET status='recovery_required' WHERE id=?",(r,))
    e.budgets.release(r,reason='restart');e.resume_run(r,background=False)
    with pytest.raises(RuntimeError): e.resume_run(r,background=False)

def test_duplicate_api_run_key_returns_same_run(tmp_path):
    e=AutomationEngine(tmp_path/'a.sqlite3',executor=Executor());w=workflow(e);a=e.run_workflow(w,context={'idempotency_key':'request-1'},background=False);b=e.run_workflow(w,context={'idempotency_key':'request-1'},background=False);assert a==b

def test_uncertain_duplicate_dispatch_requires_recovery(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3');m.reserve_run('r','w',normalize_policy({}))
    with m.enter('r',0,0):d=m.begin_dispatch('tool','external:hash');m.finish_dispatch(d,status='uncertain',uncertainty='TimeoutError')
    with m.enter('r',0,0):
        with pytest.raises(WorkflowRecoveryRequired):m.begin_dispatch('tool','external:hash')

def test_rollback_phase_has_separate_dispatch_identity(tmp_path):
    m=WorkflowBudgetManager(tmp_path/'b.sqlite3');m.reserve_run('r','w',normalize_policy({}))
    with m.enter('r',0,0,'step'):a=m.begin_dispatch('model','p');m.finish_dispatch(a)
    with m.enter('r',0,0,'rollback'):b=m.begin_dispatch('model','p');m.finish_dispatch(b)
    assert a!=b

def test_owner_status_and_redacted_decisions(tmp_path):
    e=AutomationEngine(tmp_path/'a.sqlite3',executor=Executor());w=workflow(e);r=e.run_workflow(w,background=False);s=e.runs()[0]['budget']
    assert s['policy'] and 'remaining' in s and 'concurrency_position' in s
    rendered=str(s['decision_history']).lower();assert 'prompt' not in rendered and 'api_key' not in rendered

@dataclass
class Decision: allowed:bool; requires_confirmation:bool; reason:str
@dataclass
class FakeTool: name:str; handler:object; risk:int=0
class GuardTools:
    def __init__(self):self._tools=[];self.emergency_stop=False
    def register(self,t):self._tools.append(t);return t
    def all(self):return list(self._tools)
    def effective_risk(self,t,*,parameters=None,data_classification='internal'):return t.risk
    def authorize(self,t,confirmed=False,*,parameters=None,data_classification='internal'):return Decision(True,False,'allowed')
    def set_emergency_stop(self,v):self.emergency_stop=bool(v);return self.emergency_stop
class Response:
    def __init__(self,p):self.p=p
    def json(self):return self.p
class GuardModels:
    def __init__(self):self.calls=0
    def _request(self,provider,method,path,*args,**kwargs):self.calls+=1;return Response({'usage':{'prompt_tokens':4,'completion_tokens':3,'total_tokens':7,'cost':.01}})
class GuardExecutor:
    def __init__(self):self.memory=Memory();self.models=GuardModels();self.tools=GuardTools()
    def chat(self,*a,**k):return'ok'
    def approve(self,*a,**k):return'ok'
    def reject(self,*a,**k):return'ok'

def test_actual_runtime_dispatch_guards_and_estimates(tmp_path):
    ex=GuardExecutor();m=WorkflowBudgetManager(tmp_path/'b.sqlite3');m.install_runtime_guards(ex);seen=[];t=FakeTool('write',lambda p:seen.append(p) or {'ok':True},2);ex.tools.register(t);m.reserve_run('r','w',normalize_policy({'approval_threshold':'critical'}));provider=type('P',(),{'id':'fake'})()
    with m.enter('r',0,0):ex.models._request(provider,'POST','/chat',json={'messages':[{'content':'hello'}]});t.handler({'destination':'x'})
    s=m.status('r');assert s['consumption']['model_calls']==1 and s['consumption']['tool_calls']==1 and s['consumption']['total_tokens']==7 and s['estimated_usage']['input_tokens']>0 and seen

def test_approval_threshold_forces_existing_trusted_action_path(tmp_path):
    ex=GuardExecutor();m=WorkflowBudgetManager(tmp_path/'b.sqlite3');m.install_runtime_guards(ex);t=FakeTool('external',lambda p:None,2);ex.tools.register(t);m.reserve_run('r','w',normalize_policy({'approval_threshold':'consequential'}))
    with m.enter('r',0,0):decision=ex.tools.authorize(t,parameters={'destination':'example.com'})
    assert decision.allowed is False and decision.requires_confirmation is True

def test_input_estimate_enforced_before_network_dispatch(tmp_path):
    ex=GuardExecutor();m=WorkflowBudgetManager(tmp_path/'b.sqlite3');m.install_runtime_guards(ex);m.reserve_run('r','w',normalize_policy({'max_input_tokens':6}));provider=type('P',(),{'id':'fake'})()
    with m.enter('r',0,0):
        with pytest.raises(WorkflowBudgetError,match='Input-token'):ex.models._request(provider,'POST','/chat',json={'messages':[{'content':'x'*80}]})
    assert ex.models.calls==0 and m.status('r')['confirmed_usage'] is False

class BlockingExecutor(Executor):
    def __init__(self):super().__init__();self.started=threading.Event()
    def chat(self,prompt,cancel_event=None,**kwargs):
        self.started.set()
        while cancel_event is not None and not cancel_event.wait(.01):pass
        from agent.executor import ExecutionCancelled
        raise ExecutionCancelled('cancelled')

def test_cancellation_during_dispatch_releases_slot(tmp_path):
    ex=BlockingExecutor();e=AutomationEngine(tmp_path/'a.sqlite3',executor=ex);w=workflow(e,steps=[{'kind':'prompt','prompt':'block','retries':0}]);r=e.run_workflow(w,background=True);assert ex.started.wait(2);e.cancel_run(r)
    for _ in range(100):
        if e._run(r)['status']=='cancelled':break
        time.sleep(.01)
    assert e._run(r)['status']=='cancelled' and not e.budget_status(r)['reserved_concurrency']

def test_emergency_stop_moves_active_run_to_recovery(tmp_path):
    ex=BlockingExecutor();e=AutomationEngine(tmp_path/'a.sqlite3',executor=ex);w=workflow(e,steps=[{'kind':'prompt','prompt':'block','retries':0}]);r=e.run_workflow(w,background=True);assert ex.started.wait(2);ex.tools.set_emergency_stop(True)
    for _ in range(100):
        if e._run(r)['status']=='recovery_required':break
        time.sleep(.01)
    assert e._run(r)['status']=='recovery_required' and e.budget_status(r)['stop_reason']=='Emergency Stop active' and not e.budget_status(r)['reserved_concurrency']

def test_owner_override_requires_policy_binding_and_recent_reauth(tmp_path):
    e=AutomationEngine(tmp_path/'a.sqlite3',executor=Executor());w=workflow(e,policy={'owner_override_allowed':True,'max_model_calls':1});r=e.run_workflow(w,background=False,owner_id='owner',device_id='d1',session_id='s1')
    with pytest.raises(PermissionError):e.override_run_budget(r,{'max_model_calls':2},owner_id='owner',device_id='d1',session_id='bad',reauthenticated_at=time.time())
    with pytest.raises(PermissionError):e.override_run_budget(r,{'max_model_calls':2},owner_id='owner',device_id='d1',session_id='s1')
    assert e.override_run_budget(r,{'max_model_calls':2},owner_id='owner',device_id='d1',session_id='s1',reauthenticated_at=time.time())['policy']['max_model_calls']==2


def test_restart_fences_inflight_consequential_dispatch_and_blocks_redispatch(tmp_path):
    path=tmp_path/'budget.sqlite3'
    first=WorkflowBudgetManager(path)
    first.reserve_run('r','w',normalize_policy({'max_concurrent_runs':1}))
    with first.enter('r',0,0):
        dispatch_id=first.begin_dispatch('tool','external-write:stable-hash')
    before=first.status('r')
    assert before['reserved_concurrency'] is True
    assert before['dispatches'][0]['status']=='dispatching'

    reopened=WorkflowBudgetManager(path)
    recovered=reopened.status('r')
    assert recovered['reserved_concurrency'] is False
    assert recovered['dispatches'][0]['dispatch_id']==dispatch_id
    assert recovered['dispatches'][0]['status']=='uncertain'
    assert recovered['dispatches'][0]['uncertainty']=='runtime_restart_before_dispatch_completion'
    assert 'verification/recovery required' in recovered['stop_reason'].lower()
    assert any(x.get('decision')=='recovery_required' for x in recovered['decision_history'])

    with reopened.enter('r',0,0):
        with pytest.raises(WorkflowBudgetError):
            reopened.begin_dispatch('tool','external-write:stable-hash')

    # Recovery evidence remains durable and inspectable after another restart.
    again=WorkflowBudgetManager(path).status('r')
    assert again['dispatches'][0]['status']=='uncertain'
    assert again['reserved_concurrency'] is False


def test_stage8_engine_resume_cannot_turn_uncertain_dispatch_into_redispatch(tmp_path):
    path=tmp_path/'workflow.sqlite3'; ex=Executor(); engine=AutomationEngine(path,executor=ex)
    wid=workflow(engine,steps=[{'kind':'prompt','prompt':'external consequence','retries':0}])
    rid=engine.run_workflow(wid,background=False)
    # Reconstruct the dangerous crash window at the completed step checkpoint:
    # consequential dispatch ownership exists, but its durable outcome is unknown.
    with sqlite3.connect(path) as con:
        con.execute("UPDATE workflow_runs SET status='running',current_step=0,completed_at=NULL WHERE id=?",(rid,))
    with engine.budgets._con() as con:
        con.execute("DELETE FROM workflow_dispatches WHERE run_id=?",(rid,))
        con.execute("UPDATE workflow_budget_runs SET reserved_concurrency=1,released_at=NULL,stop_reason=NULL WHERE run_id=?",(rid,))
    with engine.budgets.enter(rid,0,0):
        did=engine.budgets.begin_dispatch('tool','external-write:stable-hash')
    calls_before=ex.calls

    reopened=AutomationEngine(path,executor=ex)
    assert reopened._run(rid)['status']=='recovery_required'
    evidence=reopened.budget_status(rid)
    assert evidence['dispatches'][0]['dispatch_id']==did
    assert evidence['dispatches'][0]['status']=='uncertain'
    assert evidence['dispatches'][0]['uncertainty']=='runtime_restart_before_dispatch_completion'
    assert evidence['reserved_concurrency'] is False

    with pytest.raises(WorkflowBudgetError,match='verification/recovery required'):
        reopened.resume_run(rid,background=False)
    assert ex.calls==calls_before
    after=reopened.budget_status(rid)
    assert after['dispatches'][0]['status']=='uncertain'
    assert after['stop_reason']==evidence['stop_reason']


class RecoveryExecutor(Executor):
    def __init__(self,tmp_path):
        self.memory=Memory(); self.models=ModelStub(); self.tools=ToolRegistry(SimpleNamespace(autonomy_mode='ask',data_dir=tmp_path)); self.calls=0


def test_stage8_workflow_uncertainty_links_to_w7_and_verified_effect_advances_without_redispatch(tmp_path):
    OperatorTransactionStore(tmp_path/'operator-transactions.sqlite3')
    ex=RecoveryExecutor(tmp_path); path=tmp_path/'workflow.sqlite3'; engine=AutomationEngine(path,executor=ex)
    wid=workflow(engine,steps=[{'kind':'prompt','prompt':'external consequence','retries':0}])
    rid=engine.run_workflow(wid,background=False,owner_id='owner',device_id='device-1',session_id='session-1')
    with sqlite3.connect(path) as con:
        con.execute("UPDATE workflow_runs SET status='running',current_step=0,completed_steps_json='[]',completed_at=NULL WHERE id=?",(rid,))
    with engine.budgets._con() as con:
        con.execute("DELETE FROM workflow_dispatches WHERE run_id=?",(rid,))
        con.execute("UPDATE workflow_budget_runs SET reserved_concurrency=1,released_at=NULL,stop_reason=NULL WHERE run_id=?",(rid,))
    with engine.budgets.enter(rid,0,0):
        source_dispatch=engine.budgets.begin_dispatch('tool','external-write:stable-hash')
    calls_before=ex.calls
    reopened=AutomationEngine(path,executor=ex)
    assert reopened._run(rid)['status']=='recovery_required'
    linked=reopened.link_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
    txid=linked['recovery_transaction_id']; authority=ex.tools.ensure_recovery_authority()
    with authority._con() as con:
        dispatch=dict(con.execute('SELECT * FROM operator_dispatch_attempts WHERE transaction_id=?',(txid,)).fetchone())
    action_id=dispatch['action_id']; stamp=time.time()
    authority.record_verification(VerificationRecord(
        transaction_id=txid,action_id=action_id,dispatch_id=dispatch['dispatch_id'],
        idempotency_key=source_dispatch,operation_class='application_input',target=dispatch['target'],destination='',
        precondition={'workflow_run':rid},expected_postcondition={'effect':'occurred'},observed_postcondition={'effect':'occurred'},
        verifier_identity='stage8-test-observer',verifier_version='1',evidence_references=('audit:test',),evidence_checksum='',
        verification_timestamp=stamp,verification_fresh_until=stamp+300,result='verified_success',
        explanation='external effect independently observed',confidence=1.0))
    refreshed=reopened.refresh_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
    assert refreshed['status']=='recovery_required'
    assert reopened._run(rid)['current_step']==1
    assert reopened.budget_status(rid)['dispatches'][0]['status']=='reconciled_effect'
    assert ex.calls==calls_before
    resumed=reopened.resume_run(rid,background=False,owner_id='owner',device_id='device-1',session_id='session-1')
    assert resumed['resumed'] is True
    assert reopened._run(rid)['status']=='completed'
    assert ex.calls==calls_before


def _uncertain_recovery_run(tmp_path):
    OperatorTransactionStore(tmp_path/'operator-transactions.sqlite3'); ex=RecoveryExecutor(tmp_path); path=tmp_path/'workflow.sqlite3'; engine=AutomationEngine(path,executor=ex)
    wid=workflow(engine,steps=[{'kind':'prompt','prompt':'external consequence','retries':0}]); rid=engine.run_workflow(wid,background=False,owner_id='owner',device_id='device-1',session_id='session-1')
    with sqlite3.connect(path) as con: con.execute("UPDATE workflow_runs SET status='running',current_step=0,completed_steps_json='[]',completed_at=NULL WHERE id=?",(rid,))
    with engine.budgets._con() as con:
        con.execute("DELETE FROM workflow_dispatches WHERE run_id=?",(rid,)); con.execute("UPDATE workflow_budget_runs SET reserved_concurrency=1,released_at=NULL,stop_reason=NULL WHERE run_id=?",(rid,))
    with engine.budgets.enter(rid,0,0): source=engine.budgets.begin_dispatch('tool','external-write:stable-hash')
    reopened=AutomationEngine(path,executor=ex); linked=reopened.link_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
    return path,ex,reopened,rid,source,linked['recovery_transaction_id']


def test_stage8_workflow_recovery_link_is_idempotent_and_binding_fails_closed(tmp_path):
    path,ex,engine,rid,source,txid=_uncertain_recovery_run(tmp_path)
    again=engine.link_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
    assert again['recovery_transaction_id']==txid
    authority=ex.tools.ensure_recovery_authority()
    with authority._con() as con:
        assert con.execute('SELECT COUNT(*) FROM operator_dispatch_attempts WHERE transaction_id=?',(txid,)).fetchone()[0]==1
    for kwargs in (
        {'owner_id':'other','device_id':'device-1','session_id':'session-1'},
        {'owner_id':'owner','device_id':'other','session_id':'session-1'},
        {'owner_id':'owner','device_id':'device-1','session_id':'other'},
    ):
        with pytest.raises(PermissionError): engine.refresh_recovery(rid,**kwargs)
    assert engine.budget_status(rid)['dispatches'][0]['status']=='uncertain'


def test_stage8_workflow_recovery_owner_decision_replay_and_security_epoch_fail_closed(tmp_path):
    path,ex,engine,rid,source,txid=_uncertain_recovery_run(tmp_path); authority=ex.tools.ensure_recovery_authority()
    with pytest.raises(PermissionError,match='security_epoch_changed'):
        authority.owner_decision(txid,owner_id='owner',device_id='device-1',session_id='session-1',security_epoch=ex.tools.current_security_epoch()+1,decision='abandon_transaction',nonce='stale',reauthenticated=True)
    epoch=ex.tools.current_security_epoch()
    authority.owner_decision(txid,owner_id='owner',device_id='device-1',session_id='session-1',security_epoch=epoch,decision='abandon_transaction',nonce='once',reauthenticated=True)
    with pytest.raises(PermissionError,match='recovery_decision_replay'):
        authority.owner_decision(txid,owner_id='owner',device_id='device-1',session_id='session-1',security_epoch=epoch,decision='abandon_transaction',nonce='once',reauthenticated=True)
    engine.refresh_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
    assert engine._run(rid)['status']=='cancelled'
    assert engine.budget_status(rid)['dispatches'][0]['status']=='uncertain'


def test_stage8_verified_no_effect_retry_prohibited_stays_fenced(tmp_path):
    path,ex,engine,rid,source,txid=_uncertain_recovery_run(tmp_path); authority=ex.tools.ensure_recovery_authority()
    with authority._con() as con:
        row=dict(con.execute('SELECT * FROM operator_dispatch_attempts WHERE transaction_id=?',(txid,)).fetchone())
        con.execute("UPDATE operator_dispatch_attempts SET operation_class='email_send' WHERE dispatch_id=?",(row['dispatch_id'],))
    stamp=time.time()
    authority.record_verification(VerificationRecord(transaction_id=txid,action_id=row['action_id'],dispatch_id=row['dispatch_id'],idempotency_key=source,operation_class='email_send',target=row['target'],destination='',precondition={},expected_postcondition={},observed_postcondition={},verifier_identity='observer',verifier_version='1',evidence_references=('audit:test',),evidence_checksum='',verification_timestamp=stamp,verification_fresh_until=stamp+300,result='verified_no_effect',explanation='no effect observed',confidence=1.0))
    engine.refresh_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
    assert engine.budget_status(rid)['dispatches'][0]['status']=='uncertain'
    with pytest.raises(WorkflowBudgetError): engine.resume_run(rid,background=False,owner_id='owner',device_id='device-1',session_id='session-1')


def _verify_recovery_effect(authority,txid,source):
    with authority._con() as con: row=dict(con.execute('SELECT * FROM operator_dispatch_attempts WHERE transaction_id=?',(txid,)).fetchone())
    stamp=time.time()
    return authority.record_verification(VerificationRecord(transaction_id=txid,action_id=row['action_id'],dispatch_id=row['dispatch_id'],idempotency_key=source,operation_class=row['operation_class'],target=row['target'],destination=row['destination'],precondition={'source':source},expected_postcondition={'effect':'occurred'},observed_postcondition={'effect':'occurred'},verifier_identity='stage8-race-observer',verifier_version='1',evidence_references=('audit:race',),evidence_checksum='',verification_timestamp=stamp,verification_fresh_until=stamp+300,result='verified_success',explanation='effect independently observed',confidence=1.0))


def test_stage8_concurrent_w7_resolution_vs_resume_never_bypasses_fence(tmp_path):
    path,ex,engine,rid,source,txid=_uncertain_recovery_run(tmp_path); authority=ex.tools.ensure_recovery_authority(); calls_before=ex.calls
    barrier=threading.Barrier(2); outcomes=[]
    def resolve():
        barrier.wait()
        _verify_recovery_effect(authority,txid,source)
        engine.refresh_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
        outcomes.append('resolved')
    def resume():
        barrier.wait()
        try:
            engine.resume_run(rid,background=False,owner_id='owner',device_id='device-1',session_id='session-1'); outcomes.append('resumed')
        except (WorkflowBudgetError,RuntimeError): outcomes.append('blocked')
    a=threading.Thread(target=resolve); b=threading.Thread(target=resume); a.start(); b.start(); a.join(); b.join()
    assert 'resolved' in outcomes
    assert ex.calls==calls_before
    assert engine.budget_status(rid)['dispatches'][0]['status']=='reconciled_effect'
    # Repeated durable reconciliation is replay-safe and cannot consume the
    # recovery result into another original dispatch.
    engine.refresh_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
    assert ex.calls==calls_before
    if engine._run(rid)['status']=='recovery_required':
        engine.resume_run(rid,background=False,owner_id='owner',device_id='device-1',session_id='session-1')
    assert engine._run(rid)['status']=='completed' and ex.calls==calls_before


def test_stage8_restart_converges_from_durable_w7_resolution_before_workflow_reconcile(tmp_path):
    path,ex,engine,rid,source,txid=_uncertain_recovery_run(tmp_path); authority=ex.tools.ensure_recovery_authority(); calls_before=ex.calls
    _verify_recovery_effect(authority,txid,source)
    # Crash boundary: W7 verification is committed, but AutomationEngine has
    # not yet projected/reconciled that durable result into workflow state.
    before=engine.budget_status(rid)
    assert before['dispatches'][0]['status']=='uncertain'
    restarted=AutomationEngine(path,executor=ex)
    assert restarted._run(rid)['status']=='recovery_required'
    with pytest.raises(WorkflowBudgetError):
        restarted.resume_run(rid,background=False,owner_id='owner',device_id='device-1',session_id='session-1')
    assert ex.calls==calls_before
    restarted.refresh_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
    assert restarted.budget_status(rid)['dispatches'][0]['status']=='reconciled_effect'
    assert restarted._run(rid)['current_step']==1
    # A second restart derives the same safe state from durable W7 evidence.
    again=AutomationEngine(path,executor=ex)
    again.refresh_recovery(rid,owner_id='owner',device_id='device-1',session_id='session-1')
    assert again._run(rid)['current_step']==1
    again.resume_run(rid,background=False,owner_id='owner',device_id='device-1',session_id='session-1')
    assert again._run(rid)['status']=='completed'
    assert ex.calls==calls_before
