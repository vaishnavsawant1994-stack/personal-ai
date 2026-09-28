from __future__ import annotations

import json
import sqlite3
import time
import uuid

from recovery.operator_recovery import RecoveryAuthority, _json, _redact


class DurableRecoveryAuthority(RecoveryAuthority):
    """Final W7.6 authority extension.

    It is still the W7.1 operator transaction authority: this class only adds
    recovery tables to the same SQLite database. It intentionally permits a
    dispatch journal row to exist before the W7.4/W7.5 operator creates its
    W7.1 action row, so a crash in that boundary is recoverable rather than
    silently losing whether dispatch began.
    """

    def _init_db(self):
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            required=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='operator_transactions'").fetchone()
            if not required:
                con.rollback();raise RuntimeError('W7.1 operator transaction authority is required before W7.6 recovery')
            con.executescript('''
                CREATE TABLE IF NOT EXISTS operator_recovery(
                    transaction_id TEXT PRIMARY KEY,state TEXT NOT NULL,current_action_id TEXT NOT NULL DEFAULT '',
                    resume_position INTEGER NOT NULL DEFAULT -1,recovery_reason TEXT NOT NULL DEFAULT '',
                    owner_decision TEXT NOT NULL DEFAULT '',owner_decision_nonce TEXT NOT NULL DEFAULT '',
                    compensation_plan_json TEXT NOT NULL DEFAULT '{}',compensation_result_json TEXT NOT NULL DEFAULT '{}',
                    checkpoint_json TEXT NOT NULL DEFAULT '{}',deadline_at REAL,updated_at REAL NOT NULL,
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id)
                );
                CREATE TABLE IF NOT EXISTS operator_dispatch_attempts(
                    dispatch_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,action_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,operation_class TEXT NOT NULL,target TEXT NOT NULL DEFAULT '',
                    destination TEXT NOT NULL DEFAULT '',worker_id TEXT NOT NULL,fencing_token INTEGER NOT NULL,
                    attempt_no INTEGER NOT NULL,state TEXT NOT NULL,started_at REAL NOT NULL,dispatched_at REAL,finished_at REAL,
                    UNIQUE(transaction_id,idempotency_key),
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id)
                );
                CREATE TABLE IF NOT EXISTS operator_recovery_leases(
                    transaction_id TEXT PRIMARY KEY,worker_id TEXT NOT NULL,fencing_token INTEGER NOT NULL,
                    acquired_at REAL NOT NULL,expires_at REAL NOT NULL,
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id)
                );
                CREATE TABLE IF NOT EXISTS operator_verification_attempts(
                    verification_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,action_id TEXT NOT NULL,
                    dispatch_id TEXT NOT NULL,attempt_no INTEGER NOT NULL,result TEXT NOT NULL,
                    verifier_identity TEXT NOT NULL,verifier_version TEXT NOT NULL,precondition_json TEXT NOT NULL,
                    expected_postcondition_json TEXT NOT NULL,observed_postcondition_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,evidence_checksum TEXT NOT NULL,verified_at REAL NOT NULL,
                    fresh_until REAL NOT NULL,confidence REAL,explanation TEXT NOT NULL,UNIQUE(dispatch_id,attempt_no),
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id),
                    FOREIGN KEY(action_id) REFERENCES operator_actions(action_id),
                    FOREIGN KEY(dispatch_id) REFERENCES operator_dispatch_attempts(dispatch_id)
                );
                CREATE TABLE IF NOT EXISTS operator_compensations(
                    compensation_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,original_action_id TEXT NOT NULL,
                    compensation_action_id TEXT NOT NULL DEFAULT '',category TEXT NOT NULL,operation_class TEXT NOT NULL,
                    plan_json TEXT NOT NULL,requires_approval INTEGER NOT NULL DEFAULT 0,requires_reauth INTEGER NOT NULL DEFAULT 0,
                    permit_id TEXT NOT NULL DEFAULT '',state TEXT NOT NULL,result_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,updated_at REAL NOT NULL,
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id),
                    FOREIGN KEY(original_action_id) REFERENCES operator_actions(action_id)
                );
                CREATE TABLE IF NOT EXISTS operator_recovery_decisions(
                    decision_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,owner_id TEXT NOT NULL,device_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,security_epoch INTEGER NOT NULL,decision TEXT NOT NULL,nonce TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',created_at REAL NOT NULL,UNIQUE(transaction_id,nonce),
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id)
                );
                CREATE INDEX IF NOT EXISTS idx_recovery_state ON operator_recovery(state,updated_at);
                CREATE INDEX IF NOT EXISTS idx_dispatch_tx ON operator_dispatch_attempts(transaction_id,started_at);
                CREATE INDEX IF NOT EXISTS idx_verification_tx ON operator_verification_attempts(transaction_id,verified_at);
            ''')
            current=int(con.execute('PRAGMA user_version').fetchone()[0])
            if current<self.SCHEMA_VERSION:con.execute(f'PRAGMA user_version={self.SCHEMA_VERSION}')
            con.commit()

    @staticmethod
    def _validate_evidence_refs(refs):
        clean=[]
        for ref in refs:
            value=str(ref or '').strip()
            if not value:continue
            normalized=value.replace('\\','/')
            if '\x00' in value or any(part=='..' for part in normalized.split('/')):
                raise PermissionError('unsafe_evidence_reference')
            clean.append(value[:1000])
        return tuple(clean)

    def begin_dispatch(self,transaction_id,action_id,*,operation_class,target='',destination='',idempotency_key,worker_id,fencing_token):
        if self._emergency_stop():raise PermissionError('emergency_stop_active')
        self.assert_lease(transaction_id,worker_id,fencing_token)
        now=time.time();dispatch_id=f'dsp-{uuid.uuid4().hex}'
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');self._assert_transaction(con,transaction_id)
            prior=con.execute('SELECT * FROM operator_dispatch_attempts WHERE transaction_id=? AND idempotency_key=?',(transaction_id,idempotency_key)).fetchone()
            if prior:con.rollback();return dict(prior)
            count=int(con.execute('SELECT COUNT(*) FROM operator_dispatch_attempts WHERE action_id=?',(action_id,)).fetchone()[0])+1
            con.execute('''INSERT INTO operator_dispatch_attempts(dispatch_id,transaction_id,action_id,idempotency_key,operation_class,target,destination,worker_id,fencing_token,attempt_no,state,started_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(dispatch_id,transaction_id,action_id,idempotency_key,operation_class,str(target)[:1000],str(destination)[:1000],worker_id,int(fencing_token),count,'dispatching',now))
            con.execute('''INSERT INTO operator_recovery(transaction_id,state,current_action_id,updated_at) VALUES(?,?,?,?)
                           ON CONFLICT(transaction_id) DO UPDATE SET state=excluded.state,current_action_id=excluded.current_action_id,updated_at=excluded.updated_at''',(transaction_id,'dispatching',action_id,now));con.commit()
        return self.dispatch(dispatch_id)

    def record_verification(self,record):
        safe_refs=self._validate_evidence_refs(record.evidence_references)
        if tuple(record.evidence_references)!=safe_refs:
            from dataclasses import replace
            record=replace(record,evidence_references=safe_refs)
        return super().record_verification(record)

    def retry_decision(self,transaction_id,action_id):
        latest=self.latest_verification(transaction_id,action_id)
        with self._con() as con:
            dispatch=con.execute('SELECT * FROM operator_dispatch_attempts WHERE transaction_id=? AND action_id=? ORDER BY started_at DESC LIMIT 1',(transaction_id,action_id)).fetchone()
            action=con.execute('SELECT state FROM operator_actions WHERE transaction_id=? AND action_id=?',(transaction_id,action_id)).fetchone()
        if not dispatch:
            if action and action['state'] in {'executing','outcome_unknown','verification_failed'}:
                return {'allowed':False,'reason':'retry_not_safe'}
            return {'allowed':True,'reason':'never_dispatched'}
        if latest is None:return {'allowed':False,'reason':'retry_not_safe'}
        if float(latest['fresh_until'])<=time.time():return {'allowed':False,'reason':'stale_evidence'}
        op=str(dispatch['operation_class'])
        if latest['result']=='verified_no_effect' and op not in self._no_automatic_retry():return {'allowed':True,'reason':'verified_no_effect'}
        if latest['result']=='verified_no_effect':return {'allowed':False,'reason':'retry_requires_fresh_governance'}
        return {'allowed':False,'reason':'retry_not_safe'}

    @staticmethod
    def _no_automatic_retry():
        from recovery.operator_recovery import NO_AUTOMATIC_RETRY
        return NO_AUTOMATIC_RETRY

    def authorize_compensation(self,compensation_id,*,permit_id,reauthenticated=False,policy_operation=None):
        if self._emergency_stop():raise PermissionError('emergency_stop_active')
        row=self.compensation(compensation_id)
        if not row:raise KeyError(compensation_id)
        if row['category'] in {'manual_recovery_only','irreversible'}:raise PermissionError('compensation_not_automatable')
        if row['requires_approval'] and not permit_id:raise PermissionError('compensation_requires_approval')
        if row['requires_reauth'] and not reauthenticated:raise PermissionError('reauthentication_required')
        if self.policy_gateway is not None:
            if policy_operation is None:raise PermissionError('compensation_policy_operation_required')
            decision=self.policy_gateway.evaluate(policy_operation,approved=True,reauthenticated=reauthenticated)
            if getattr(getattr(decision,'decision',None),'value',getattr(decision,'decision',None))!='allow':
                raise PermissionError('compensation_policy_denied')
            if not permit_id or not self.policy_gateway.consume_temporary_permit(permit_id,policy_operation,decision):
                raise PermissionError('compensation_permit_invalid_or_replayed')
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');con.execute("UPDATE operator_compensations SET permit_id=?,state='authorized',updated_at=? WHERE compensation_id=?",(str(permit_id),time.time(),compensation_id));con.commit()
        return self.compensation(compensation_id)

    def link_compensation_action(self,compensation_id,compensation_action_id):
        row=self.compensation(compensation_id)
        if not row:raise KeyError(compensation_id)
        if compensation_action_id==row['original_action_id']:raise PermissionError('compensation_action_must_be_separate')
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');self._assert_action(con,row['transaction_id'],compensation_action_id)
            con.execute("UPDATE operator_compensations SET compensation_action_id=?,state='executing',updated_at=? WHERE compensation_id=?",(compensation_action_id,time.time(),compensation_id));con.commit()
        return self.compensation(compensation_id)

    def record_compensation_result(self,compensation_id,verification_id):
        row=self.compensation(compensation_id)
        if not row:raise KeyError(compensation_id)
        if not row['compensation_action_id']:raise PermissionError('compensation_action_not_linked')
        verification=self.verification(verification_id)
        if not verification or verification['action_id']!=row['compensation_action_id'] or verification['transaction_id']!=row['transaction_id']:
            raise PermissionError('compensation_verification_mismatch')
        result=verification['result']
        state={'verified_success':'compensated','verified_partial':'compensation_partial','verified_failure':'compensation_failed','verified_no_effect':'compensation_failed'}.get(result,'recovery_review_required')
        payload={'verification_id':verification_id,'result':result,'evidence_checksum':verification['evidence_checksum']}
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');con.execute('UPDATE operator_compensations SET state=?,result_json=?,updated_at=? WHERE compensation_id=?',(state,_json(_redact(payload)),time.time(),compensation_id));
            if state=='recovery_review_required':con.execute("UPDATE operator_recovery SET state='recovery_review_required',recovery_reason='compensation_outcome_uncertain',updated_at=? WHERE transaction_id=?",(time.time(),row['transaction_id']))
            con.commit()
        return self.compensation(compensation_id)
