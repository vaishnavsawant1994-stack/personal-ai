from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable

VERIFICATION_RESULTS = {
    'verified_success', 'verified_no_effect', 'verified_partial', 'verified_failure',
    'unknown_outcome', 'cancelled_before_dispatch', 'blocked_before_dispatch',
    'recovery_review_required',
}
RECOVERY_STATES = {
    'active', 'waiting_for_approval', 'dispatching', 'dispatched', 'verifying',
    'verified_success', 'verified_no_effect', 'partially_completed',
    'compensation_available', 'compensation_requires_approval',
    'recovery_review_required', 'cancelled', 'failed', 'completed',
    'abandoned_by_owner',
}
TERMINAL_RECOVERY_STATES = {'cancelled', 'failed', 'completed', 'abandoned_by_owner'}
COMPENSATION_CATEGORIES = {
    'automatically_reversible', 'compensation_available', 'manual_recovery_only', 'irreversible'
}
CONSEQUENTIAL_OPERATIONS = {
    'form_submission', 'email_send', 'message_send', 'external_upload', 'share',
    'public_publish', 'delete', 'destructive_delete', 'permission_change',
    'security_setting_modify', 'purchase', 'financial_transfer', 'legal_acceptance',
}
NO_AUTOMATIC_RETRY = CONSEQUENTIAL_OPERATIONS | {'application_input'}
CRITICAL_COMPENSATION = {
    'delete', 'destructive_delete', 'permission_change', 'security_setting_modify',
    'purchase', 'financial_transfer', 'legal_acceptance', 'public_publish',
}
SAFE_OWNER_STATES = {
    'verification_pending', 'verification_failed', 'verified_no_effect',
    'partially_completed', 'retry_not_safe', 'compensation_available',
    'compensation_requires_approval', 'compensation_failed',
    'recovery_review_required', 'transaction_abandoned', 'emergency_stop_active',
}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            low = str(key).lower()
            if any(word in low for word in ('token', 'password', 'secret', 'cookie', 'authorization', 'clipboard_content', 'raw_content', 'dom', 'screenshot_bytes')):
                continue
            out[str(key)] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    return value


@dataclass(frozen=True)
class VerificationRecord:
    transaction_id: str
    action_id: str
    dispatch_id: str
    idempotency_key: str
    operation_class: str
    target: str
    destination: str
    precondition: dict[str, Any]
    expected_postcondition: dict[str, Any]
    observed_postcondition: dict[str, Any]
    verifier_identity: str
    verifier_version: str
    evidence_references: tuple[str, ...]
    evidence_checksum: str
    verification_timestamp: float
    verification_fresh_until: float
    result: str
    explanation: str
    confidence: float | None = None

    def __post_init__(self):
        if self.result not in VERIFICATION_RESULTS:
            raise ValueError('invalid verification result')
        if not self.transaction_id or not self.action_id or not self.dispatch_id or not self.idempotency_key:
            raise ValueError('verification record binding is incomplete')
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError('confidence must be objectively bounded from 0 to 1')


class RecoveryAuthority:
    """W7.6 durable recovery extension over the authoritative W7.1 transaction database.

    This class never creates a transaction or approval. Existing W7.1 transaction/action rows
    must exist first. Trusted Action Core remains the approval authority and W7.3 remains policy
    authority for retry/compensation dispatch.
    """

    SCHEMA_VERSION = 73

    def __init__(
        self,
        path: str | Path,
        *,
        emergency_stop: Callable[[], bool] | None = None,
        policy_gateway=None,
        security_epoch_provider: Callable[[], int] | None = None,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._emergency_stop = emergency_stop or (lambda: False)
        self.policy_gateway = policy_gateway
        self._security_epoch_provider = security_epoch_provider
        self._init_db()
        self.recover_expired_leases()

    def _con(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        return con

    def _init_db(self):
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            # W7.1 authority must exist; W7.6 is an extension, never a parallel engine.
            required = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='operator_transactions'").fetchone()
            if not required:
                con.rollback()
                raise RuntimeError('W7.1 operator transaction authority is required before W7.6 recovery')
            con.executescript('''
                CREATE TABLE IF NOT EXISTS operator_recovery(
                    transaction_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    current_action_id TEXT NOT NULL DEFAULT '',
                    resume_position INTEGER NOT NULL DEFAULT -1,
                    recovery_reason TEXT NOT NULL DEFAULT '',
                    owner_decision TEXT NOT NULL DEFAULT '',
                    owner_decision_nonce TEXT NOT NULL DEFAULT '',
                    compensation_plan_json TEXT NOT NULL DEFAULT '{}',
                    compensation_result_json TEXT NOT NULL DEFAULT '{}',
                    checkpoint_json TEXT NOT NULL DEFAULT '{}',
                    deadline_at REAL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id)
                );
                CREATE TABLE IF NOT EXISTS operator_dispatch_attempts(
                    dispatch_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    operation_class TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    destination TEXT NOT NULL DEFAULT '',
                    worker_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    dispatched_at REAL,
                    finished_at REAL,
                    UNIQUE(transaction_id,idempotency_key),
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id),
                    FOREIGN KEY(action_id) REFERENCES operator_actions(action_id)
                );
                CREATE TABLE IF NOT EXISTS operator_recovery_leases(
                    transaction_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    acquired_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id)
                );
                CREATE TABLE IF NOT EXISTS operator_verification_attempts(
                    verification_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    dispatch_id TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    result TEXT NOT NULL,
                    verifier_identity TEXT NOT NULL,
                    verifier_version TEXT NOT NULL,
                    precondition_json TEXT NOT NULL,
                    expected_postcondition_json TEXT NOT NULL,
                    observed_postcondition_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    evidence_checksum TEXT NOT NULL,
                    verified_at REAL NOT NULL,
                    fresh_until REAL NOT NULL,
                    confidence REAL,
                    explanation TEXT NOT NULL,
                    UNIQUE(dispatch_id,attempt_no),
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id),
                    FOREIGN KEY(action_id) REFERENCES operator_actions(action_id),
                    FOREIGN KEY(dispatch_id) REFERENCES operator_dispatch_attempts(dispatch_id)
                );
                CREATE TABLE IF NOT EXISTS operator_compensations(
                    compensation_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    original_action_id TEXT NOT NULL,
                    compensation_action_id TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL,
                    operation_class TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    requires_approval INTEGER NOT NULL DEFAULT 0,
                    requires_reauth INTEGER NOT NULL DEFAULT 0,
                    permit_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id),
                    FOREIGN KEY(original_action_id) REFERENCES operator_actions(action_id)
                );
                CREATE TABLE IF NOT EXISTS operator_recovery_decisions(
                    decision_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    security_epoch INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    UNIQUE(transaction_id,nonce),
                    FOREIGN KEY(transaction_id) REFERENCES operator_transactions(transaction_id)
                );
                CREATE INDEX IF NOT EXISTS idx_recovery_state ON operator_recovery(state,updated_at);
                CREATE INDEX IF NOT EXISTS idx_dispatch_tx ON operator_dispatch_attempts(transaction_id,started_at);
                CREATE INDEX IF NOT EXISTS idx_verification_tx ON operator_verification_attempts(transaction_id,verified_at);
            ''')
            current = int(con.execute('PRAGMA user_version').fetchone()[0])
            if current < self.SCHEMA_VERSION:
                con.execute(f'PRAGMA user_version={self.SCHEMA_VERSION}')
            con.commit()

    def schema_version(self) -> int:
        with self._con() as con:
            return int(con.execute('PRAGMA user_version').fetchone()[0])

    def _assert_transaction(self, con, transaction_id: str):
        row = con.execute('SELECT * FROM operator_transactions WHERE transaction_id=?', (transaction_id,)).fetchone()
        if not row:
            raise KeyError(transaction_id)
        return dict(row)

    def transaction_binding(self, transaction_id: str) -> dict | None:
        """Read the canonical W7.1 owner/device/session binding without exposing plan/content."""
        with self._con() as con:
            row = con.execute(
                'SELECT owner_id,device_id,session_id,security_epoch FROM operator_transactions WHERE transaction_id=?',
                (str(transaction_id),),
            ).fetchone()
        return dict(row) if row else None

    def _assert_action(self, con, transaction_id: str, action_id: str):
        row = con.execute('SELECT * FROM operator_actions WHERE action_id=? AND transaction_id=?', (action_id, transaction_id)).fetchone()
        if not row:
            raise KeyError(action_id)
        return dict(row)

    def ensure_recovery(self, transaction_id: str, *, state: str='active', reason: str='') -> dict:
        if state not in RECOVERY_STATES:
            raise ValueError('invalid recovery state')
        now = time.time()
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            self._assert_transaction(con, transaction_id)
            con.execute('''INSERT OR IGNORE INTO operator_recovery(transaction_id,state,recovery_reason,updated_at)
                           VALUES(?,?,?,?)''', (transaction_id, state, str(reason)[:500], now))
            if reason:
                con.execute('UPDATE operator_recovery SET recovery_reason=?,updated_at=? WHERE transaction_id=?', (str(reason)[:500], now, transaction_id))
            con.commit()
        return self.recovery(transaction_id)

    def recovery(self, transaction_id: str) -> dict | None:
        with self._con() as con:
            row = con.execute('SELECT * FROM operator_recovery WHERE transaction_id=?', (transaction_id,)).fetchone()
        if not row:
            return None
        out = dict(row)
        for key in ('checkpoint_json','compensation_plan_json','compensation_result_json'):
            try:
                out[key[:-5]] = json.loads(out.pop(key))
            except Exception:
                out[key[:-5]] = {}
        return out

    def set_state(self, transaction_id: str, state: str, *, reason: str='', current_action_id: str='', resume_position: int | None=None, checkpoint: dict | None=None) -> dict:
        if state not in RECOVERY_STATES:
            raise ValueError('invalid recovery state')
        now=time.time()
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            self._assert_transaction(con,transaction_id)
            con.execute('INSERT OR IGNORE INTO operator_recovery(transaction_id,state,updated_at) VALUES(?,?,?)',(transaction_id,'active',now))
            fields=['state=?','updated_at=?']; values=[state,now]
            if reason: fields.append('recovery_reason=?'); values.append(str(reason)[:500])
            if current_action_id: fields.append('current_action_id=?'); values.append(current_action_id)
            if resume_position is not None: fields.append('resume_position=?'); values.append(int(resume_position))
            if checkpoint is not None: fields.append('checkpoint_json=?'); values.append(_json(_redact(checkpoint)))
            values.append(transaction_id)
            con.execute(f"UPDATE operator_recovery SET {','.join(fields)} WHERE transaction_id=?",tuple(values));con.commit()
        return self.recovery(transaction_id)

    def acquire_lease(self, transaction_id: str, worker_id: str, *, ttl_seconds: int=30) -> dict:
        if not worker_id:
            raise ValueError('worker identity required')
        if self._emergency_stop():
            raise PermissionError('emergency_stop_active')
        now=time.time(); expiry=now+max(5,int(ttl_seconds))
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE'); self._assert_transaction(con,transaction_id)
            row=con.execute('SELECT * FROM operator_recovery_leases WHERE transaction_id=?',(transaction_id,)).fetchone()
            if row and float(row['expires_at'])>now and row['worker_id']!=worker_id:
                con.rollback(); raise RuntimeError('recovery_lease_held')
            token=(int(row['fencing_token'])+1) if row else 1
            con.execute('''INSERT INTO operator_recovery_leases(transaction_id,worker_id,fencing_token,acquired_at,expires_at)
                           VALUES(?,?,?,?,?) ON CONFLICT(transaction_id) DO UPDATE SET worker_id=excluded.worker_id,
                           fencing_token=excluded.fencing_token,acquired_at=excluded.acquired_at,expires_at=excluded.expires_at''',(transaction_id,worker_id,token,now,expiry));con.commit()
        return {'transaction_id':transaction_id,'worker_id':worker_id,'fencing_token':token,'expires_at':expiry}

    def assert_lease(self, transaction_id: str, worker_id: str, fencing_token: int) -> dict:
        with self._con() as con:
            row=con.execute('SELECT * FROM operator_recovery_leases WHERE transaction_id=?',(transaction_id,)).fetchone()
        if not row or row['worker_id']!=worker_id or int(row['fencing_token'])!=int(fencing_token) or float(row['expires_at'])<=time.time():
            raise RuntimeError('stale_or_invalid_fencing_token')
        return dict(row)

    def release_lease(self, transaction_id: str, worker_id: str, fencing_token: int) -> bool:
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            cur=con.execute('DELETE FROM operator_recovery_leases WHERE transaction_id=? AND worker_id=? AND fencing_token=?',(transaction_id,worker_id,int(fencing_token)));con.commit();return bool(cur.rowcount)

    def recover_expired_leases(self) -> int:
        now=time.time()
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');rows=con.execute('SELECT transaction_id FROM operator_recovery_leases WHERE expires_at<=?',(now,)).fetchall();con.execute('DELETE FROM operator_recovery_leases WHERE expires_at<=?',(now,));con.commit();return len(rows)

    def begin_dispatch(self, transaction_id: str, action_id: str, *, operation_class: str, target: str='', destination: str='', idempotency_key: str, worker_id: str, fencing_token: int) -> dict:
        if self._emergency_stop():
            raise PermissionError('emergency_stop_active')
        self.assert_lease(transaction_id,worker_id,fencing_token)
        now=time.time(); dispatch_id=f'dsp-{uuid.uuid4().hex}'
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');self._assert_transaction(con,transaction_id);self._assert_action(con,transaction_id,action_id)
            prior=con.execute('SELECT * FROM operator_dispatch_attempts WHERE transaction_id=? AND idempotency_key=?',(transaction_id,idempotency_key)).fetchone()
            if prior:
                con.rollback();return dict(prior)
            count=int(con.execute('SELECT COUNT(*) FROM operator_dispatch_attempts WHERE action_id=?',(action_id,)).fetchone()[0])+1
            con.execute('''INSERT INTO operator_dispatch_attempts(dispatch_id,transaction_id,action_id,idempotency_key,operation_class,target,destination,worker_id,fencing_token,attempt_no,state,started_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(dispatch_id,transaction_id,action_id,idempotency_key,operation_class,str(target)[:1000],str(destination)[:1000],worker_id,int(fencing_token),count,'dispatching',now))
            con.execute('''INSERT INTO operator_recovery(transaction_id,state,current_action_id,updated_at) VALUES(?,?,?,?)
                           ON CONFLICT(transaction_id) DO UPDATE SET state=excluded.state,current_action_id=excluded.current_action_id,updated_at=excluded.updated_at''',(transaction_id,'dispatching',action_id,now));con.commit()
        return self.dispatch(dispatch_id)

    def mark_dispatched(self, dispatch_id: str, *, worker_id: str, fencing_token: int) -> dict:
        now=time.time()
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');row=con.execute('SELECT * FROM operator_dispatch_attempts WHERE dispatch_id=?',(dispatch_id,)).fetchone()
            if not row: con.rollback();raise KeyError(dispatch_id)
            self.assert_lease(row['transaction_id'],worker_id,fencing_token)
            if row['worker_id']!=worker_id or int(row['fencing_token'])!=int(fencing_token):con.rollback();raise RuntimeError('stale_or_invalid_fencing_token')
            con.execute("UPDATE operator_dispatch_attempts SET state='dispatched',dispatched_at=? WHERE dispatch_id=?",(now,dispatch_id));con.execute("UPDATE operator_recovery SET state='dispatched',updated_at=? WHERE transaction_id=?",(now,row['transaction_id']));con.commit()
        return self.dispatch(dispatch_id)

    def dispatch(self, dispatch_id: str) -> dict | None:
        with self._con() as con: row=con.execute('SELECT * FROM operator_dispatch_attempts WHERE dispatch_id=?',(dispatch_id,)).fetchone()
        return dict(row) if row else None

    def record_verification(self, record: VerificationRecord) -> dict:
        evidence_material={'references':list(record.evidence_references),'precondition':_redact(record.precondition),'expected':_redact(record.expected_postcondition),'observed':_redact(record.observed_postcondition)}
        calculated=_digest(evidence_material)
        if record.evidence_checksum and record.evidence_checksum!=calculated:
            raise PermissionError('tampered_evidence')
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');self._assert_transaction(con,record.transaction_id);self._assert_action(con,record.transaction_id,record.action_id)
            dispatch=con.execute('SELECT * FROM operator_dispatch_attempts WHERE dispatch_id=? AND transaction_id=? AND action_id=?',(record.dispatch_id,record.transaction_id,record.action_id)).fetchone()
            if not dispatch:con.rollback();raise KeyError(record.dispatch_id)
            attempt=int(con.execute('SELECT COUNT(*) FROM operator_verification_attempts WHERE dispatch_id=?',(record.dispatch_id,)).fetchone()[0])+1
            vid=f'ver-{uuid.uuid4().hex}'
            con.execute('''INSERT INTO operator_verification_attempts(verification_id,transaction_id,action_id,dispatch_id,attempt_no,result,verifier_identity,verifier_version,precondition_json,expected_postcondition_json,observed_postcondition_json,evidence_refs_json,evidence_checksum,verified_at,fresh_until,confidence,explanation)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(vid,record.transaction_id,record.action_id,record.dispatch_id,attempt,record.result,record.verifier_identity,record.verifier_version,_json(_redact(record.precondition)),_json(_redact(record.expected_postcondition)),_json(_redact(record.observed_postcondition)),_json(list(record.evidence_references)),calculated,float(record.verification_timestamp),float(record.verification_fresh_until),record.confidence,str(record.explanation)[:1000]))
            state=self._recovery_state_for_result(record.result)
            con.execute("UPDATE operator_dispatch_attempts SET state=?,finished_at=? WHERE dispatch_id=?",(record.result,time.time(),record.dispatch_id))
            con.execute('''INSERT INTO operator_recovery(transaction_id,state,current_action_id,recovery_reason,updated_at) VALUES(?,?,?,?,?)
                           ON CONFLICT(transaction_id) DO UPDATE SET state=excluded.state,current_action_id=excluded.current_action_id,recovery_reason=excluded.recovery_reason,updated_at=excluded.updated_at''',(record.transaction_id,state,record.action_id,'' if record.result=='verified_success' else record.result,time.time()));con.commit()
        return self.verification(vid)

    @staticmethod
    def _recovery_state_for_result(result: str) -> str:
        return {
            'verified_success':'verified_success','verified_no_effect':'verified_no_effect','verified_partial':'partially_completed',
            'verified_failure':'failed','unknown_outcome':'recovery_review_required','cancelled_before_dispatch':'cancelled',
            'blocked_before_dispatch':'failed','recovery_review_required':'recovery_review_required',
        }[result]

    def verification(self, verification_id: str) -> dict | None:
        with self._con() as con:row=con.execute('SELECT * FROM operator_verification_attempts WHERE verification_id=?',(verification_id,)).fetchone()
        if not row:return None
        out=dict(row)
        for key in ('precondition_json','expected_postcondition_json','observed_postcondition_json','evidence_refs_json'):
            try:out[key[:-5]]=json.loads(out.pop(key))
            except Exception:out[key[:-5]]={} if key!='evidence_refs_json' else []
        return out

    def latest_verification(self, transaction_id: str, action_id: str | None=None) -> dict | None:
        sql='SELECT verification_id FROM operator_verification_attempts WHERE transaction_id=?';args=[transaction_id]
        if action_id:sql+=' AND action_id=?';args.append(action_id)
        sql+=' ORDER BY verified_at DESC,attempt_no DESC LIMIT 1'
        with self._con() as con:row=con.execute(sql,tuple(args)).fetchone()
        return self.verification(row['verification_id']) if row else None

    def retry_decision(self, transaction_id: str, action_id: str) -> dict:
        latest=self.latest_verification(transaction_id,action_id)
        with self._con() as con:
            dispatch=con.execute('SELECT * FROM operator_dispatch_attempts WHERE transaction_id=? AND action_id=? ORDER BY started_at DESC LIMIT 1',(transaction_id,action_id)).fetchone()
        if not dispatch:
            return {'allowed':True,'reason':'never_dispatched'}
        op=str(dispatch['operation_class'])
        if latest is None:
            return {'allowed':False,'reason':'retry_not_safe'}
        if latest['result']=='verified_no_effect' and op not in NO_AUTOMATIC_RETRY:
            return {'allowed':True,'reason':'verified_no_effect'}
        if latest['result']=='verified_no_effect':
            return {'allowed':False,'reason':'retry_requires_fresh_governance'}
        return {'allowed':False,'reason':'retry_not_safe'}

    def plan_compensation(self, transaction_id: str, original_action_id: str, *, category: str, operation_class: str, plan: dict) -> dict:
        if category not in COMPENSATION_CATEGORIES:raise ValueError('invalid compensation category')
        if category=='automatically_reversible' and operation_class in CONSEQUENTIAL_OPERATIONS:raise PermissionError('consequential_compensation_cannot_be_automatic')
        latest=self.latest_verification(transaction_id,original_action_id)
        if latest is None or latest['result'] in {'unknown_outcome','recovery_review_required'}:raise PermissionError('compensation_requires_verified_original_outcome')
        requires_approval=category=='compensation_available' or operation_class in CONSEQUENTIAL_OPERATIONS
        requires_reauth=operation_class in CRITICAL_COMPENSATION
        cid=f'cmp-{uuid.uuid4().hex}';now=time.time()
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');self._assert_action(con,transaction_id,original_action_id)
            con.execute('''INSERT INTO operator_compensations(compensation_id,transaction_id,original_action_id,category,operation_class,plan_json,requires_approval,requires_reauth,state,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(cid,transaction_id,original_action_id,category,operation_class,_json(_redact(plan)),1 if requires_approval else 0,1 if requires_reauth else 0,'planned',now,now))
            state='compensation_requires_approval' if requires_approval else 'compensation_available'
            con.execute("UPDATE operator_recovery SET state=?,compensation_plan_json=?,updated_at=? WHERE transaction_id=?",(state,_json(_redact(plan)),now,transaction_id));con.commit()
        return self.compensation(cid)

    def compensation(self, compensation_id: str) -> dict | None:
        with self._con() as con:row=con.execute('SELECT * FROM operator_compensations WHERE compensation_id=?',(compensation_id,)).fetchone()
        if not row:return None
        out=dict(row);out['requires_approval']=bool(out['requires_approval']);out['requires_reauth']=bool(out['requires_reauth'])
        for key in ('plan_json','result_json'):
            try:out[key[:-5]]=json.loads(out.pop(key))
            except Exception:out[key[:-5]]={}
        return out

    def authorize_compensation(self, compensation_id: str, *, permit_id: str, reauthenticated: bool=False) -> dict:
        if self._emergency_stop():raise PermissionError('emergency_stop_active')
        row=self.compensation(compensation_id)
        if not row:raise KeyError(compensation_id)
        if row['category'] in {'manual_recovery_only','irreversible'}:raise PermissionError('compensation_not_automatable')
        if row['requires_approval'] and not permit_id:raise PermissionError('compensation_requires_approval')
        if row['requires_reauth'] and not reauthenticated:raise PermissionError('reauthentication_required')
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');con.execute("UPDATE operator_compensations SET permit_id=?,state='authorized',updated_at=? WHERE compensation_id=?",(str(permit_id),time.time(),compensation_id));con.commit()
        return self.compensation(compensation_id)

    def owner_decision(self, transaction_id: str, *, owner_id: str, device_id: str, session_id: str, security_epoch: int, decision: str, nonce: str, reauthenticated: bool=False, details: dict | None=None) -> dict:
        allowed={'verify_again','resume_from_safe_checkpoint','retry_after_verified_no_effect','approve_compensation','mark_externally_completed','abandon_transaction','cancel_remaining_steps','export_recovery_report'}
        if decision not in allowed:raise ValueError('unsupported_recovery_decision')
        if not owner_id or not device_id or not session_id or not nonce:raise PermissionError('owner_device_session_binding_required')
        if decision in {'resume_from_safe_checkpoint','retry_after_verified_no_effect','approve_compensation','mark_externally_completed','abandon_transaction','cancel_remaining_steps'} and not reauthenticated:
            raise PermissionError('reauthentication_required')
        if self._security_epoch_provider is not None and int(security_epoch)!=int(self._security_epoch_provider()):raise PermissionError('security_epoch_changed')
        if self._emergency_stop() and decision not in {'verify_again','export_recovery_report','abandon_transaction'}:raise PermissionError('emergency_stop_active')
        now=time.time();did=f'dec-{uuid.uuid4().hex}'
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');tx=self._assert_transaction(con,transaction_id)
            if tx['owner_id']!=owner_id or tx['device_id']!=device_id or tx['session_id']!=session_id:con.rollback();raise PermissionError('owner_device_session_mismatch')
            try:
                con.execute('''INSERT INTO operator_recovery_decisions(decision_id,transaction_id,owner_id,device_id,session_id,security_epoch,decision,nonce,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',(did,transaction_id,owner_id,device_id,session_id,int(security_epoch),decision,nonce,_json(_redact(details or {})),now))
            except sqlite3.IntegrityError:
                con.rollback();raise PermissionError('recovery_decision_replay')
            state=None
            if decision=='abandon_transaction':state='abandoned_by_owner'
            elif decision=='cancel_remaining_steps':state='cancelled'
            elif decision=='mark_externally_completed':state='completed'
            if state:
                con.execute("UPDATE operator_recovery SET state=?,owner_decision=?,owner_decision_nonce=?,updated_at=? WHERE transaction_id=?",(state,decision,nonce,now,transaction_id))
            else:
                con.execute("UPDATE operator_recovery SET owner_decision=?,owner_decision_nonce=?,updated_at=? WHERE transaction_id=?",(decision,nonce,now,transaction_id))
            con.commit()
        return {'decision_id':did,'transaction_id':transaction_id,'decision':decision,'state':(self.recovery(transaction_id) or {}).get('state','')}

    def emergency_stop_snapshot(self) -> int:
        """Preserve evidence, invalidate active recovery dispatch state and release leases.

        Trusted Action Core invalidates permits by advancing the security epoch in ToolRegistry.
        Clearing Emergency Stop does not resume any transaction.
        """
        now=time.time()
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            rows=con.execute("SELECT transaction_id FROM operator_recovery WHERE state NOT IN ('completed','cancelled','failed','abandoned_by_owner')").fetchall()
            for row in rows:
                con.execute("UPDATE operator_recovery SET state='recovery_review_required',recovery_reason='emergency_stop_active',updated_at=? WHERE transaction_id=?",(now,row['transaction_id']))
            con.execute('DELETE FROM operator_recovery_leases');con.commit();return len(rows)

    def owner_view(self, transaction_id: str) -> dict:
        with self._con() as con:
            tx=con.execute('SELECT transaction_id,goal,state,checkpoint_index,updated_at,error_code,recovery_reason FROM operator_transactions WHERE transaction_id=?',(transaction_id,)).fetchone()
            if not tx:raise KeyError(transaction_id)
            actions=con.execute('SELECT action_id,sequence,kind,state,verified,error_code,started_at,completed_at,target_identity FROM operator_actions WHERE transaction_id=? ORDER BY sequence',(transaction_id,)).fetchall()
            verifications=con.execute('SELECT verification_id,action_id,result,verifier_identity,verifier_version,evidence_refs_json,evidence_checksum,verified_at,fresh_until,explanation FROM operator_verification_attempts WHERE transaction_id=? ORDER BY verified_at',(transaction_id,)).fetchall()
            comps=con.execute('SELECT compensation_id,original_action_id,category,operation_class,requires_approval,requires_reauth,state,updated_at FROM operator_compensations WHERE transaction_id=? ORDER BY created_at',(transaction_id,)).fetchall()
            audits=con.execute('SELECT id,action_id,event,created_at FROM operator_audit WHERE transaction_id=? ORDER BY id DESC LIMIT 50',(transaction_id,)).fetchall()
        recovery=self.recovery(transaction_id) or {'state':'active','recovery_reason':''}
        return {
            'transaction_goal':tx['goal'], 'transaction_id':transaction_id,
            'transaction_state':tx['state'], 'recovery_state':recovery.get('state'),
            'completed_steps':[dict(a) for a in actions if a['state']=='verified'],
            'current_step':recovery.get('current_action_id') or '',
            'affected_targets':[str(a['target_identity']) for a in actions if a['target_identity']],
            'verified':[dict(v) for v in verifications if v['result']=='verified_success'],
            'uncertain':[dict(v) for v in verifications if v['result'] in {'unknown_outcome','verified_partial','recovery_review_required'}],
            'redacted_evidence':[{'verification_id':v['verification_id'],'evidence_checksum':v['evidence_checksum'],'evidence_references':json.loads(v['evidence_refs_json'] or '[]'),'verified_at':v['verified_at'],'fresh_until':v['fresh_until']} for v in verifications],
            'proposed_recovery_options':['verify_again','resume_from_safe_checkpoint','retry_after_verified_no_effect','approve_compensation','mark_externally_completed','abandon_transaction','cancel_remaining_steps','export_recovery_report'],
            'rollback_limitations':[{'compensation_id':c['compensation_id'],'category':c['category'],'requires_approval':bool(c['requires_approval']),'requires_reauth':bool(c['requires_reauth']),'state':c['state']} for c in comps],
            'recovery_reason':recovery.get('recovery_reason',''),
            'timestamps':{'transaction_updated_at':tx['updated_at'],'recovery_updated_at':recovery.get('updated_at')},
            'audit_references':[dict(a) for a in audits],
        }

    def export_report(self, transaction_id: str) -> dict:
        view=self.owner_view(transaction_id)
        return {'report':view,'checksum':_digest(view),'exported_at':time.time()}
