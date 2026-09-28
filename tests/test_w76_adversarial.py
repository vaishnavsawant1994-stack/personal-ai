from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

import pytest

from desktop.operator_transactions import OperatorBinding,OperatorTransactionStore
from recovery.cross_operator import CrossOperatorOrchestrator
from recovery.operator_recovery import RecoveryAuthority,VerificationRecord,_digest


def setup_action(tmp_path):
    path=tmp_path/'operator.sqlite3';store=OperatorTransactionStore(path);binding=OperatorBinding('owner','device','session',0)
    store.propose('tx',binding,goal='adversarial',action_plan={'steps':[{'sequence':0,'kind':'action'}]});store.transition('tx','policy_check');store.transition('tx','permitted');store.transition('tx','executing');store.start_action('tx',0,kind='action',parameter_hash='x',expected_postcondition='done')
    return path,store,RecoveryAuthority(path,security_epoch_provider=lambda:0)


def add_verification(recovery,result='verified_success',operation='file_copy'):
    lease=recovery.acquire_lease('tx','w');d=recovery.begin_dispatch('tx','tx:0',operation_class=operation,idempotency_key='k',worker_id='w',fencing_token=lease['fencing_token']);recovery.mark_dispatched(d['dispatch_id'],worker_id='w',fencing_token=lease['fencing_token'])
    pre={'before':'x'};expected={'after':'y'};observed={'after':'y' if result=='verified_success' else 'x'};refs=['obs1'];material={'references':refs,'precondition':pre,'expected':expected,'observed':observed}
    rec=VerificationRecord('tx','tx:0',d['dispatch_id'],'k',operation,'','',pre,expected,observed,'test','1',tuple(refs),_digest(material),time.time(),time.time()+60,result,'safe',1.0 if result in {'verified_success','verified_no_effect','verified_failure'} else None)
    out=recovery.record_verification(rec);recovery.release_lease('tx','w',lease['fencing_token']);return out


def test_crash_before_dispatch_is_retryable(tmp_path):
    path,store,recovery=setup_action(tmp_path)
    assert recovery.retry_decision('tx','tx:0')['reason']=='never_dispatched'


def test_crash_during_dispatch_without_verification_is_not_retryable(tmp_path):
    path,store,recovery=setup_action(tmp_path);lease=recovery.acquire_lease('tx','w');recovery.begin_dispatch('tx','tx:0',operation_class='file_copy',idempotency_key='k',worker_id='w',fencing_token=lease['fencing_token'])
    assert recovery.retry_decision('tx','tx:0')=={'allowed':False,'reason':'retry_not_safe'}


def test_crash_after_dispatch_without_verification_is_not_retryable(tmp_path):
    path,store,recovery=setup_action(tmp_path);lease=recovery.acquire_lease('tx','w');d=recovery.begin_dispatch('tx','tx:0',operation_class='file_copy',idempotency_key='k',worker_id='w',fencing_token=lease['fencing_token']);recovery.mark_dispatched(d['dispatch_id'],worker_id='w',fencing_token=lease['fencing_token'])
    assert recovery.retry_decision('tx','tx:0')['allowed'] is False


def test_restart_during_approval_wait_preserves_w71_state(tmp_path):
    path=tmp_path/'operator.sqlite3';store=OperatorTransactionStore(path);binding=OperatorBinding('owner','device','session',0);store.propose('tx',binding,goal='wait',action_plan={'steps':[{'sequence':0,'kind':'action'}]});store.transition('tx','policy_check');store.transition('tx','approval_required')
    RecoveryAuthority(path);again=OperatorTransactionStore(path);assert again.transaction('tx')['state']=='approval_required'


def test_duplicate_workers_cannot_recover_same_transaction(tmp_path):
    path,store,recovery=setup_action(tmp_path);recovery.acquire_lease('tx','w1')
    with pytest.raises(RuntimeError):recovery.acquire_lease('tx','w2')


def test_fencing_token_mismatch_blocks_dispatch(tmp_path):
    path,store,recovery=setup_action(tmp_path);lease=recovery.acquire_lease('tx','w')
    with pytest.raises(RuntimeError):recovery.begin_dispatch('tx','tx:0',operation_class='file_copy',idempotency_key='k',worker_id='w',fencing_token=lease['fencing_token']+1)


def test_duplicate_submit_send_upload_not_auto_retry(tmp_path):
    for op in ('form_submission','email_send','message_send','external_upload','public_publish'):
        sub=tmp_path/op;sub.mkdir();path,store,recovery=setup_action(sub);add_verification(recovery,'verified_no_effect',op);assert recovery.retry_decision('tx','tx:0')['allowed'] is False


def test_partial_file_copy_enters_partial_state(tmp_path):
    path,store,recovery=setup_action(tmp_path);add_verification(recovery,'verified_partial','file_copy');assert recovery.recovery('tx')['state']=='partially_completed'


def test_partial_move_rename_enters_partial_state(tmp_path):
    path,store,recovery=setup_action(tmp_path);add_verification(recovery,'verified_partial','file_move');assert recovery.owner_view('tx')['uncertain']

@pytest.mark.parametrize('reason',['disk_full','locked_file','browser_tab_closed','application_closed','foreground_window_changed','network_loss','verification_timeout','missing_evidence'])
def test_environment_failure_reason_can_be_preserved_without_blind_retry(tmp_path,reason):
    path,store,recovery=setup_action(tmp_path);recovery.ensure_recovery('tx');recovery.set_state('tx','recovery_review_required',reason=reason)
    assert recovery.recovery('tx')['recovery_reason']==reason;assert recovery.retry_decision('tx','tx:0')['allowed'] is True


def test_stale_evidence_is_visible_as_stale(tmp_path):
    path,store,recovery=setup_action(tmp_path);lease=recovery.acquire_lease('tx','w');d=recovery.begin_dispatch('tx','tx:0',operation_class='file_copy',idempotency_key='k',worker_id='w',fencing_token=lease['fencing_token']);recovery.mark_dispatched(d['dispatch_id'],worker_id='w',fencing_token=lease['fencing_token'])
    pre={};expected={};observed={};refs=['obs'];material={'references':refs,'precondition':pre,'expected':expected,'observed':observed};past=time.time()-100
    rec=VerificationRecord('tx','tx:0',d['dispatch_id'],'k','file_copy','','',pre,expected,observed,'test','1',tuple(refs),_digest(material),past,past+1,'verified_success','old',1.0);out=recovery.record_verification(rec);assert out['fresh_until']<time.time()


def test_owner_decision_requires_recent_reauth(tmp_path):
    path,store,recovery=setup_action(tmp_path);recovery.ensure_recovery('tx')
    with pytest.raises(PermissionError,match='reauthentication'):recovery.owner_decision('tx',owner_id='owner',device_id='device',session_id='session',security_epoch=0,decision='cancel_remaining_steps',nonce='x')


def test_emergency_stop_does_not_auto_resume_when_cleared(tmp_path):
    active={'v':True};path,store,recovery=setup_action(tmp_path);recovery._emergency_stop=lambda:active['v'];recovery.ensure_recovery('tx');recovery.emergency_stop_snapshot();active['v']=False
    assert recovery.recovery('tx')['state']=='recovery_review_required'


def test_manual_and_irreversible_compensation_never_authorize(tmp_path):
    for category in ('manual_recovery_only','irreversible'):
        sub=tmp_path/category;sub.mkdir();path,store,recovery=setup_action(sub);add_verification(recovery);cmp=recovery.plan_compensation('tx','tx:0',category=category,operation_class='local_move',plan={'manual':True})
        with pytest.raises(PermissionError,match='not_automatable'):recovery.authorize_compensation(cmp['compensation_id'],permit_id='permit',reauthenticated=True)


def test_compensation_failure_is_recordable_without_claiming_rollback(tmp_path):
    path,store,recovery=setup_action(tmp_path);add_verification(recovery);cmp=recovery.plan_compensation('tx','tx:0',category='compensation_available',operation_class='local_move',plan={'kind':'move_back'})
    with sqlite3.connect(path) as con:con.execute("UPDATE operator_compensations SET state='compensation_failed',result_json=? WHERE compensation_id=?",('{"safe_error":"locked_file"}',cmp['compensation_id']))
    assert recovery.compensation(cmp['compensation_id'])['state']=='compensation_failed'


def test_restart_recovery_repeated_twice_preserves_records(tmp_path):
    path,store,recovery=setup_action(tmp_path);add_verification(recovery);a=RecoveryAuthority(path);b=RecoveryAuthority(path);assert a.owner_view('tx')['verified'];assert b.owner_view('tx')['verified']


def test_audit_view_excludes_raw_payload_values(tmp_path):
    path,store,recovery=setup_action(tmp_path);add_verification(recovery);text=str(recovery.owner_view('tx'))
    assert 'password=' not in text and 'authorization:' not in text


def test_cross_operator_recipes_do_not_introduce_unrestricted_capabilities(tmp_path):
    path,store,recovery=setup_action(tmp_path);o=CrossOperatorOrchestrator(recovery)
    assert o.browser_download_recipe(origin='https://example.com',filename='a.pdf',mime='application/pdf',checksum='x',approved_folder='/safe')['steps'][-1]=='verify_completion'
    assert 'verify_output_checksum_or_version' in o.file_application_recipe(file_path='/safe/a',application_identity='app')['steps']
    assert 'request_trusted_action_approval' in o.knowledge_upload_recipe(file_path='/safe/a',origin='https://example.com')['steps']
    assert o.extraction_report_recipe(origin='https://example.com',report_path='/safe/r')['steps'][-1]=='stop_before_external_share_without_approval'


@dataclass
class FakeAction:
    transaction_id:str='tx';sequence:int=0

class FakeResult:
    def __init__(self,status,reason_code='allow'):self.status=status;self.reason_code=reason_code;self.transaction_id='tx';self.before_observation_id='before';self.after_observation_id='after';self.result={}

class FakeOperator:
    def __init__(self,status='completed'):self.status=status
    def execute(self,action,**kwargs):return FakeResult(self.status)


def test_crash_recovery_verifies_read_only_before_resume(tmp_path):
    path,store,recovery=setup_action(tmp_path);orch=CrossOperatorOrchestrator(recovery)
    out=orch.recover_after_crash('tx','tx:0',lambda:{'verification_result':'verified_no_effect'})
    assert out['retry_safe'] is True and out['resume_safe'] is True


def test_unknown_read_only_recovery_requires_review(tmp_path):
    path,store,recovery=setup_action(tmp_path);orch=CrossOperatorOrchestrator(recovery)
    out=orch.recover_after_crash('tx','tx:0',lambda:{'verification_result':'unknown_outcome'})
    assert out['state']=='recovery_review_required' and out['retry_safe'] is False
