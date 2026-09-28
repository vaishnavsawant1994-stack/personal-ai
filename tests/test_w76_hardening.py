from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

import pytest

from desktop.operator_transactions import OperatorBinding,OperatorTransactionStore
from recovery.cross_operator import CrossOperatorOrchestrator
from recovery.operator_recovery import VerificationRecord,_digest
from recovery.recovery_authority import DurableRecoveryAuthority


def tx_store(tmp_path,*,with_action=True):
    path=tmp_path/'operator.sqlite3';store=OperatorTransactionStore(path);binding=OperatorBinding('owner','device','session',0)
    store.propose('tx',binding,goal='hardening',action_plan={'steps':[{'sequence':0,'kind':'file_copy'}]});store.transition('tx','policy_check');store.transition('tx','permitted');store.transition('tx','executing')
    if with_action:store.start_action('tx',0,kind='file_copy',parameter_hash='p',expected_postcondition='done')
    return path,store,DurableRecoveryAuthority(path,security_epoch_provider=lambda:0)


def record(recovery,result='verified_no_effect',fresh=60):
    lease=recovery.acquire_lease('tx','w');d=recovery.begin_dispatch('tx','tx:0',operation_class='file_copy',idempotency_key='k',worker_id='w',fencing_token=lease['fencing_token']);recovery.mark_dispatched(d['dispatch_id'],worker_id='w',fencing_token=lease['fencing_token'])
    pre={};expected={};observed={};refs=('obs',);material={'references':list(refs),'precondition':pre,'expected':expected,'observed':observed};now=time.time()
    vr=VerificationRecord('tx','tx:0',d['dispatch_id'],'k','file_copy','','',pre,expected,observed,'hardening','1',refs,_digest(material),now,now+fresh,result,'safe',1.0 if result in {'verified_success','verified_no_effect','verified_failure'} else None)
    out=recovery.record_verification(vr);recovery.release_lease('tx','w',lease['fencing_token']);return out


def test_pre_dispatch_journal_does_not_require_action_row(tmp_path):
    path,store,recovery=tx_store(tmp_path,with_action=False);lease=recovery.acquire_lease('tx','w')
    row=recovery.begin_dispatch('tx','tx:0',operation_class='file_copy',idempotency_key='pre',worker_id='w',fencing_token=lease['fencing_token'])
    assert row['state']=='dispatching'


def test_unknown_w71_executing_action_without_dispatch_is_not_retryable(tmp_path):
    path,store,recovery=tx_store(tmp_path,with_action=True)
    assert recovery.retry_decision('tx','tx:0')=={'allowed':False,'reason':'retry_not_safe'}


def test_stale_verified_no_effect_cannot_enable_retry(tmp_path):
    path,store,recovery=tx_store(tmp_path);record(recovery,'verified_no_effect',fresh=-1)
    assert recovery.retry_decision('tx','tx:0')=={'allowed':False,'reason':'stale_evidence'}


def test_evidence_traversal_reference_is_rejected(tmp_path):
    path,store,recovery=tx_store(tmp_path);lease=recovery.acquire_lease('tx','w');d=recovery.begin_dispatch('tx','tx:0',operation_class='file_copy',idempotency_key='k',worker_id='w',fencing_token=lease['fencing_token']);recovery.mark_dispatched(d['dispatch_id'],worker_id='w',fencing_token=lease['fencing_token'])
    refs=('../secret',);material={'references':list(refs),'precondition':{},'expected':{},'observed':{}};now=time.time()
    vr=VerificationRecord('tx','tx:0',d['dispatch_id'],'k','file_copy','','',{}, {}, {},'hardening','1',refs,_digest(material),now,now+60,'verified_success','safe',1.0)
    with pytest.raises(PermissionError,match='unsafe_evidence_reference'):recovery.record_verification(vr)


def test_partial_migration_resume_is_additive(tmp_path):
    path=tmp_path/'operator.sqlite3';store=OperatorTransactionStore(path)
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE operator_recovery(transaction_id TEXT PRIMARY KEY,state TEXT NOT NULL,current_action_id TEXT NOT NULL DEFAULT '',resume_position INTEGER NOT NULL DEFAULT -1,recovery_reason TEXT NOT NULL DEFAULT '',owner_decision TEXT NOT NULL DEFAULT '',owner_decision_nonce TEXT NOT NULL DEFAULT '',compensation_plan_json TEXT NOT NULL DEFAULT '{}',compensation_result_json TEXT NOT NULL DEFAULT '{}',checkpoint_json TEXT NOT NULL DEFAULT '{}',deadline_at REAL,updated_at REAL NOT NULL)")
    recovery=DurableRecoveryAuthority(path);assert recovery.schema_version()==73
    with sqlite3.connect(path) as con:names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'operator_dispatch_attempts','operator_recovery_leases','operator_verification_attempts','operator_compensations','operator_recovery_decisions'}<=names


def test_restart_runtime_reasserts_schema_73_after_w71_init(tmp_path):
    path,store,recovery=tx_store(tmp_path);assert recovery.schema_version()==73
    OperatorTransactionStore(path)
    restarted=DurableRecoveryAuthority(path)
    assert restarted.schema_version()==73


@dataclass
class Action:
    transaction_id:str='tx';sequence:int=0

class ExistingOperator:
    def __init__(self,store):self.store=store
    def execute(self,action,**kwargs):
        self.store.start_action('tx',0,kind='file_copy',parameter_hash='runtime',expected_postcondition='done')
        self.store.finish_action('tx:0',verified=True,evidence={'checksum':'ok'})
        return {'status':'completed','reason_code':'allow','result':{'evidence_ref':'obs-safe'}}


def test_cross_operator_can_journal_before_existing_operator_creates_action(tmp_path):
    path,store,recovery=tx_store(tmp_path,with_action=False);orch=CrossOperatorOrchestrator(recovery)
    out=orch.execute_step(ExistingOperator(store),Action(),operation_class='file_copy')
    assert out['w76_verification']['result']=='verified_success'


class Kind:
    value='allow'
class Decision:
    decision=Kind()
class FakePolicy:
    def __init__(self):self.consumed=[]
    def evaluate(self,operation,**kwargs):return Decision()
    def consume_temporary_permit(self,permit_id,operation,decision):
        if permit_id in self.consumed:return False
        self.consumed.append(permit_id);return permit_id=='one-use'


def test_compensation_requires_w73_policy_and_consumes_one_use_permit(tmp_path):
    path,store,recovery=tx_store(tmp_path);record(recovery,'verified_success');policy=FakePolicy();recovery.policy_gateway=policy
    cmp=recovery.plan_compensation('tx','tx:0',category='compensation_available',operation_class='local_move',plan={'kind':'move_back'})
    with pytest.raises(PermissionError,match='policy_operation_required'):recovery.authorize_compensation(cmp['compensation_id'],permit_id='one-use',reauthenticated=True)
    operation=object();assert recovery.authorize_compensation(cmp['compensation_id'],permit_id='one-use',reauthenticated=True,policy_operation=operation)['state']=='authorized'
    with pytest.raises(PermissionError,match='replayed'):recovery.authorize_compensation(cmp['compensation_id'],permit_id='one-use',reauthenticated=True,policy_operation=operation)
