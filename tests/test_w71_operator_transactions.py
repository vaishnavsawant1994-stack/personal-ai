import json
import threading
import time

import pytest

from desktop.operator_transactions import OperatorBinding, OperatorTransactionStore


PLAN = {'summary': 'test', 'steps': [{'kind': 'click', 'params': {'x': 10, 'y': 20}, 'reason': 'test', 'verify': 'done'}]}
BINDING = OperatorBinding('owner', 'device-1', 'session-1', 7, 'conversation-1', 'workflow-1')


def prepare(store, txid='tx-1', *, deadline_at=None):
    tx, created = store.propose(txid, BINDING, goal='click the test control', action_plan=PLAN, deadline_at=deadline_at)
    if created:
        store.transition(txid, 'policy_check')
        store.transition(txid, 'approval_required')
    return store.transaction(txid)


def test_state_machine_and_binding_are_durable(tmp_path):
    path = tmp_path / 'operator.sqlite3'
    store = OperatorTransactionStore(path)
    tx = prepare(store)
    assert tx['state'] == 'approval_required'
    assert tx['owner_id'] == 'owner'
    assert tx['device_id'] == 'device-1'
    assert tx['session_id'] == 'session-1'
    assert tx['security_epoch'] == 7
    assert tx['conversation_id'] == 'conversation-1'
    assert tx['workflow_id'] == 'workflow-1'
    reopened = OperatorTransactionStore(path)
    assert reopened.transaction('tx-1')['state'] == 'approval_required'


def test_binding_mismatch_fails_closed(tmp_path):
    store = OperatorTransactionStore(tmp_path / 'operator.sqlite3'); prepare(store)
    for bad in (
        OperatorBinding('other', 'device-1', 'session-1', 7),
        OperatorBinding('owner', 'other', 'session-1', 7),
        OperatorBinding('owner', 'device-1', 'other', 7),
        OperatorBinding('owner', 'device-1', 'session-1', 8),
    ):
        with pytest.raises(PermissionError, match='binding mismatch'):
            store.assert_binding('tx-1', bad)


def test_transaction_id_is_idempotent_but_cannot_be_rebound(tmp_path):
    store = OperatorTransactionStore(tmp_path / 'operator.sqlite3')
    first, created = store.propose('same', BINDING, goal='goal', action_plan=PLAN)
    assert created is True
    again, created = store.propose('same', BINDING, goal='goal', action_plan=PLAN)
    assert created is False and again['plan_hash'] == first['plan_hash']
    with pytest.raises(PermissionError, match='already bound'):
        store.propose('same', BINDING, goal='different', action_plan=PLAN)


def test_concurrent_proposal_creates_one_transaction(tmp_path):
    store = OperatorTransactionStore(tmp_path / 'operator.sqlite3')
    results=[]; errors=[]
    def worker():
        try: results.append(store.propose('race', BINDING, goal='goal', action_plan=PLAN)[1])
        except Exception as exc: errors.append(exc)
    threads=[threading.Thread(target=worker) for _ in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert errors == []
    assert results.count(True) == 1
    assert results.count(False) == 3


def test_action_checkpoint_is_idempotent_and_parameter_bound(tmp_path):
    store = OperatorTransactionStore(tmp_path / 'operator.sqlite3'); prepare(store)
    store.transition('tx-1', 'permitted'); store.transition('tx-1', 'executing')
    action, created = store.start_action('tx-1', 1, kind='click', parameter_hash='abc', expected_postcondition='done')
    assert created is True and action['state'] == 'executing'
    same, created = store.start_action('tx-1', 1, kind='click', parameter_hash='abc', expected_postcondition='done')
    assert created is False and same['action_id'] == action['action_id']
    with pytest.raises(PermissionError, match='different parameters'):
        store.start_action('tx-1', 1, kind='click', parameter_hash='changed', expected_postcondition='done')
    store.finish_action(action['action_id'], verified=True, evidence={'screen_sha256': 'safe-hash'})
    assert store.actions('tx-1')[0]['verified'] is True
    assert store.transaction('tx-1')['checkpoint_index'] == 1


def test_restart_moves_uncertain_execution_to_recovery_review(tmp_path):
    path=tmp_path/'operator.sqlite3'; store=OperatorTransactionStore(path); prepare(store)
    store.transition('tx-1','permitted'); store.transition('tx-1','executing')
    action,_=store.start_action('tx-1',1,kind='click',parameter_hash='abc',expected_postcondition='done')
    reopened=OperatorTransactionStore(path)
    assert reopened.transaction('tx-1')['state']=='recovery_review_required'
    assert reopened.actions('tx-1')[0]['state']=='outcome_unknown'
    with pytest.raises(RuntimeError,match='recovery review'):
        reopened.assert_dispatchable('tx-1',BINDING)


def test_cancellation_and_deadline_fail_closed(tmp_path):
    store=OperatorTransactionStore(tmp_path/'operator.sqlite3'); prepare(store)
    store.transition('tx-1','permitted'); assert store.request_cancel('tx-1') is True
    with pytest.raises(RuntimeError,match='cancelled'):
        store.assert_dispatchable('tx-1',BINDING)
    expired=OperatorTransactionStore(tmp_path/'expired.sqlite3')
    prepare(expired,'expired',deadline_at=time.time()-1); expired.transition('expired','permitted')
    with pytest.raises(TimeoutError,match='deadline'):
        expired.assert_dispatchable('expired',BINDING)


def test_invalid_transitions_are_rejected(tmp_path):
    store=OperatorTransactionStore(tmp_path/'operator.sqlite3'); prepare(store)
    with pytest.raises(RuntimeError,match='invalid operator transition'):
        store.transition('tx-1','completed')


def test_operator_audit_redacts_sensitive_key_classes(tmp_path):
    store=OperatorTransactionStore(tmp_path/'operator.sqlite3'); prepare(store)
    with store._con() as con:
        store._audit(con,'tx-1','test',payload={'token':'secret-token','clipboard_text':'secret-value','safe_count':3}); con.commit()
    payload=json.loads(store.audit('tx-1')[-1]['payload_json'])
    assert payload == {'safe_count':3}
