from __future__ import annotations

import sqlite3
import time

import pytest

from desktop.operator_transactions import OperatorBinding,OperatorTransactionStore
from recovery.operator_recovery import RecoveryAuthority,VerificationRecord,_digest


def seeded(tmp_path, *, state='permitted'):
    path=tmp_path/'operator.sqlite3';store=OperatorTransactionStore(path);binding=OperatorBinding('owner','device','session',0)
    store.propose('tx1',binding,goal='test recovery',action_plan={'steps':[{'sequence':0,'kind':'copy'}]})
    store.transition('tx1','policy_check');store.transition('tx1','permitted')
    if state=='executing':store.transition('tx1','executing')
    if state in {'executing','action'}:
        store.start_action('tx1',0,kind='copy',parameter_hash='p',expected_postcondition='exists')
    recovery=RecoveryAuthority(path,security_epoch_provider=lambda:0)
    return path,store,binding,recovery


def verification(result='verified_success', *, checksum=True, ts=None):
    now=time.time() if ts is None else ts
    material={'references':['obs-before','obs-after'],'precondition':{'exists':False},'expected':{'exists':True},'observed':{'exists':result=='verified_success'}}
    return VerificationRecord('tx1','tx1:0','dispatch','idem','file_copy','a','b',material['precondition'],material['expected'],material['observed'],'unit','1',tuple(material['references']),_digest(material) if checksum else 'bad',now,now+60,result,'safe explanation',1.0 if result in {'verified_success','verified_no_effect','verified_failure'} else None)


def dispatched(tmp_path, *, operation='file_copy'):
    path,store,binding,recovery=seeded(tmp_path,state='action');lease=recovery.acquire_lease('tx1','worker',ttl_seconds=30)
    row=recovery.begin_dispatch('tx1','tx1:0',operation_class=operation,target='a',destination='b',idempotency_key='idem',worker_id='worker',fencing_token=lease['fencing_token'])
    recovery.mark_dispatched(row['dispatch_id'],worker_id='worker',fencing_token=lease['fencing_token'])
    return path,store,binding,recovery,lease,row


def test_schema_72_upgrades_additively_to_73(tmp_path):
    path,store,binding,recovery=seeded(tmp_path)
    assert recovery.schema_version()==73
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT COUNT(*) FROM operator_transactions").fetchone()[0]==1
        names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'operator_recovery','operator_dispatch_attempts','operator_recovery_leases','operator_verification_attempts','operator_compensations','operator_recovery_decisions'}<=names


def test_repeated_initialization_and_restart_safe(tmp_path):
    path,store,binding,recovery=seeded(tmp_path)
    RecoveryAuthority(path);RecoveryAuthority(path)
    assert RecoveryAuthority(path).schema_version()==73


def test_requires_existing_w71_authority(tmp_path):
    with pytest.raises(RuntimeError,match='W7.1'):
        RecoveryAuthority(tmp_path/'empty.sqlite3')


def test_recovery_does_not_create_parallel_transaction(tmp_path):
    path,store,binding,recovery=seeded(tmp_path)
    with pytest.raises(KeyError):recovery.ensure_recovery('missing')


def test_lease_is_durable_and_exclusive(tmp_path):
    path,store,binding,recovery=seeded(tmp_path)
    one=recovery.acquire_lease('tx1','a',ttl_seconds=30)
    with pytest.raises(RuntimeError,match='lease_held'):recovery.acquire_lease('tx1','b',ttl_seconds=30)
    same=recovery.acquire_lease('tx1','a',ttl_seconds=30)
    assert same['fencing_token']==one['fencing_token']+1


def test_stale_fencing_token_rejected(tmp_path):
    path,store,binding,recovery=seeded(tmp_path)
    first=recovery.acquire_lease('tx1','worker',ttl_seconds=30);second=recovery.acquire_lease('tx1','worker',ttl_seconds=30)
    with pytest.raises(RuntimeError,match='fencing'):recovery.assert_lease('tx1','worker',first['fencing_token'])
    recovery.assert_lease('tx1','worker',second['fencing_token'])


def test_expired_lease_can_be_recovered(tmp_path):
    path,store,binding,recovery=seeded(tmp_path)
    recovery.acquire_lease('tx1','worker',ttl_seconds=5)
    with sqlite3.connect(path) as con:con.execute("UPDATE operator_recovery_leases SET expires_at=?",(time.time()-1,))
    assert recovery.recover_expired_leases()==1
    assert recovery.acquire_lease('tx1','new',ttl_seconds=30)['worker_id']=='new'


def test_duplicate_idempotency_returns_same_dispatch(tmp_path):
    path,store,binding,recovery=seeded(tmp_path,state='action');lease=recovery.acquire_lease('tx1','worker')
    one=recovery.begin_dispatch('tx1','tx1:0',operation_class='file_copy',idempotency_key='same',worker_id='worker',fencing_token=lease['fencing_token'])
    two=recovery.begin_dispatch('tx1','tx1:0',operation_class='file_copy',idempotency_key='same',worker_id='worker',fencing_token=lease['fencing_token'])
    assert one['dispatch_id']==two['dispatch_id']


def test_verification_contract_persists_all_required_binding(tmp_path):
    path,store,binding,recovery,lease,row=dispatched(tmp_path)
    rec=verification();rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id']})
    out=recovery.record_verification(rec)
    assert out['result']=='verified_success';assert out['verifier_identity']=='unit';assert out['evidence_checksum'];assert out['fresh_until']>out['verified_at']

@pytest.mark.parametrize('result,state',[('verified_success','verified_success'),('verified_no_effect','verified_no_effect'),('verified_partial','partially_completed'),('verified_failure','failed'),('unknown_outcome','recovery_review_required'),('cancelled_before_dispatch','cancelled'),('blocked_before_dispatch','failed'),('recovery_review_required','recovery_review_required')])
def test_verification_result_state_mapping(tmp_path,result,state):
    path,store,binding,recovery,lease,row=dispatched(tmp_path)
    rec=verification(result);rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id']})
    recovery.record_verification(rec)
    assert recovery.recovery('tx1')['state']==state


def test_tampered_evidence_rejected(tmp_path):
    path,store,binding,recovery,lease,row=dispatched(tmp_path)
    rec=verification(checksum=False);rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id']})
    with pytest.raises(PermissionError,match='tampered_evidence'):recovery.record_verification(rec)


def test_retry_never_dispatched_is_safe(tmp_path):
    path,store,binding,recovery=seeded(tmp_path,state='action')
    assert recovery.retry_decision('tx1','tx1:0')=={'allowed':True,'reason':'never_dispatched'}


def test_retry_only_after_verified_no_effect_for_nonconsequential(tmp_path):
    path,store,binding,recovery,lease,row=dispatched(tmp_path,operation='file_copy')
    rec=verification('verified_no_effect');rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id'],'operation_class':'file_copy'})
    recovery.record_verification(rec)
    assert recovery.retry_decision('tx1','tx1:0')['allowed'] is True


def test_external_send_never_automatically_retries(tmp_path):
    path,store,binding,recovery,lease,row=dispatched(tmp_path,operation='email_send')
    rec=verification('verified_no_effect');rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id'],'operation_class':'email_send'})
    recovery.record_verification(rec)
    assert recovery.retry_decision('tx1','tx1:0')=={'allowed':False,'reason':'retry_requires_fresh_governance'}


def test_unknown_outcome_blocks_compensation(tmp_path):
    path,store,binding,recovery,lease,row=dispatched(tmp_path)
    rec=verification('unknown_outcome');rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id']})
    recovery.record_verification(rec)
    with pytest.raises(PermissionError,match='verified_original_outcome'):recovery.plan_compensation('tx1','tx1:0',category='compensation_available',operation_class='delete',plan={'kind':'restore'})


def test_low_risk_compensation_can_be_automatic(tmp_path):
    path,store,binding,recovery,lease,row=dispatched(tmp_path)
    rec=verification();rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id']});recovery.record_verification(rec)
    cmp=recovery.plan_compensation('tx1','tx1:0',category='automatically_reversible',operation_class='local_move',plan={'kind':'move_back'})
    assert cmp['requires_approval'] is False;assert cmp['requires_reauth'] is False


def test_consequential_compensation_cannot_be_automatic(tmp_path):
    path,store,binding,recovery,lease,row=dispatched(tmp_path)
    rec=verification();rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id']});recovery.record_verification(rec)
    with pytest.raises(PermissionError):recovery.plan_compensation('tx1','tx1:0',category='automatically_reversible',operation_class='delete',plan={'kind':'recreate'})


def test_compensation_approval_and_reauth_are_separate(tmp_path):
    path,store,binding,recovery,lease,row=dispatched(tmp_path)
    rec=verification();rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id']});recovery.record_verification(rec)
    cmp=recovery.plan_compensation('tx1','tx1:0',category='compensation_available',operation_class='delete',plan={'kind':'restore'})
    assert cmp['requires_approval'] and cmp['requires_reauth']
    with pytest.raises(PermissionError,match='approval'):recovery.authorize_compensation(cmp['compensation_id'],permit_id='',reauthenticated=True)
    with pytest.raises(PermissionError,match='reauthentication'):recovery.authorize_compensation(cmp['compensation_id'],permit_id='one-use',reauthenticated=False)
    assert recovery.authorize_compensation(cmp['compensation_id'],permit_id='one-use',reauthenticated=True)['state']=='authorized'


def test_owner_decision_is_bound_and_replay_protected(tmp_path):
    path,store,binding,recovery=seeded(tmp_path);recovery.ensure_recovery('tx1')
    out=recovery.owner_decision('tx1',owner_id='owner',device_id='device',session_id='session',security_epoch=0,decision='abandon_transaction',nonce='n1',reauthenticated=True)
    assert out['state']=='abandoned_by_owner'
    with pytest.raises(PermissionError,match='replay'):recovery.owner_decision('tx1',owner_id='owner',device_id='device',session_id='session',security_epoch=0,decision='abandon_transaction',nonce='n1',reauthenticated=True)


def test_owner_device_session_mismatch_rejected(tmp_path):
    path,store,binding,recovery=seeded(tmp_path);recovery.ensure_recovery('tx1')
    with pytest.raises(PermissionError,match='mismatch'):recovery.owner_decision('tx1',owner_id='owner',device_id='other',session_id='session',security_epoch=0,decision='abandon_transaction',nonce='n',reauthenticated=True)


def test_security_epoch_change_rejected(tmp_path):
    path,store,binding,recovery=seeded(tmp_path);recovery._security_epoch_provider=lambda:2;recovery.ensure_recovery('tx1')
    with pytest.raises(PermissionError,match='security_epoch'):recovery.owner_decision('tx1',owner_id='owner',device_id='device',session_id='session',security_epoch=0,decision='abandon_transaction',nonce='n',reauthenticated=True)


def test_emergency_stop_blocks_dispatch_and_marks_review(tmp_path):
    active={'v':False};path,store,binding,recovery=seeded(tmp_path,state='action');recovery._emergency_stop=lambda:active['v'];recovery.ensure_recovery('tx1');active['v']=True
    assert recovery.emergency_stop_snapshot()==1
    assert recovery.recovery('tx1')['state']=='recovery_review_required'
    with pytest.raises(PermissionError,match='emergency_stop'):recovery.acquire_lease('tx1','w')


def test_owner_view_is_redacted_and_structured(tmp_path):
    path,store,binding,recovery,lease,row=dispatched(tmp_path)
    rec=verification();rec=VerificationRecord(**{**rec.__dict__,'dispatch_id':row['dispatch_id']});recovery.record_verification(rec)
    view=recovery.owner_view('tx1')
    assert view['transaction_goal']=='test recovery';assert view['verified'];assert 'proposed_recovery_options' in view;assert 'audit_references' in view
    exported=recovery.export_report('tx1');assert len(exported['checksum'])==64
