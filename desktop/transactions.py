from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

STATES = {
    'proposed','policy_check','approval_required','permitted','executing','verifying',
    'completed','failed','cancelled','recovery_review_required',
}
TERMINAL_STATES = {'completed','failed','cancelled','recovery_review_required'}


def _safe_json(value) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(',', ':'), default=str)


def _hash(value) -> str:
    return hashlib.sha256(_safe_json(value).encode('utf-8')).hexdigest()


@dataclass
class DesktopAction:
    id: str
    kind: str
    params: dict
    undo: dict | None = None
    verified: bool = False
    state: str = 'proposed'
    ordinal: int = 0


@dataclass
class DesktopTransaction:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    actions: list[DesktopAction] = field(default_factory=list)
    committed: bool = False
    created_at: float = field(default_factory=time.time)
    state: str = 'proposed'
    owner_id: str = 'owner'
    device_id: str | None = None
    session_id: str | None = None
    security_epoch: int = 0
    execution_id: str = ''
    conversation_id: str | None = None
    workflow_id: str | None = None
    goal_hash: str = ''
    plan_hash: str = ''


class DesktopTransactionManager:
    """Durable operator ledger for bounded desktop actions.

    Approval remains owned by Trusted Action Core. This store records the
    already-authorized binding and guarantees that restart/recovery never
    silently redispatches an action whose outcome may be uncertain.
    """

    def __init__(self, controller, path: Path | None = None):
        self.controller = controller
        self.path = Path(path) if path is not None else None
        self.active = {}
        self._lock = threading.RLock()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
            self._recover_interrupted()

    def _con(self):
        if self.path is None:
            raise RuntimeError('durable operator database is not configured')
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self):
        with self._con() as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS operator_transactions(
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                device_id TEXT,
                session_id TEXT,
                security_epoch INTEGER NOT NULL,
                execution_id TEXT NOT NULL,
                conversation_id TEXT,
                workflow_id TEXT,
                goal_hash TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_operator_tx_state
                ON operator_transactions(state, updated_at);
            CREATE TABLE IF NOT EXISTS operator_actions(
                id TEXT PRIMARY KEY,
                transaction_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                kind TEXT NOT NULL,
                parameter_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                undo_json TEXT,
                verified INTEGER NOT NULL DEFAULT 0,
                dispatched_at REAL,
                verified_at REAL,
                error_type TEXT,
                UNIQUE(transaction_id, ordinal),
                FOREIGN KEY(transaction_id) REFERENCES operator_transactions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS operator_state_history(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT NOT NULL,
                action_id TEXT,
                state TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            ''')

    def _history(self, tx_id: str, state: str, *, action_id=None, reason=''):
        if state not in STATES:
            raise ValueError(f'invalid operator state: {state}')
        if self.path is None:
            return
        with self._con() as con:
            con.execute(
                'INSERT INTO operator_state_history(transaction_id,action_id,state,reason,created_at) VALUES(?,?,?,?,?)',
                (tx_id, action_id, state, str(reason or '')[:500], time.time()),
            )

    def _recover_interrupted(self):
        """Never redispatch work after restart; uncertain work requires review."""
        with self._lock, self._con() as con:
            rows = con.execute(
                "SELECT id,state FROM operator_transactions WHERE state IN ('executing','verifying')"
            ).fetchall()
            now = time.time()
            for row in rows:
                con.execute(
                    "UPDATE operator_transactions SET state='recovery_review_required',updated_at=?,last_error=? WHERE id=?",
                    (now, 'process_restarted_with_uncertain_outcome', row['id']),
                )
                con.execute(
                    "INSERT INTO operator_state_history(transaction_id,state,reason,created_at) VALUES(?,?,?,?)",
                    (row['id'], 'recovery_review_required', 'restart_after_dispatch', now),
                )

    def begin(self, *, context=None, goal='', plan=None):
        context = dict(context or {})
        tx = DesktopTransaction(
            owner_id=str(context.get('owner_id') or 'owner'),
            device_id=context.get('device_id'),
            session_id=context.get('session_id'),
            security_epoch=int(context.get('security_epoch') or 0),
            execution_id=str(context.get('execution_id') or ''),
            conversation_id=context.get('conversation_id'),
            workflow_id=context.get('workflow_id'),
            goal_hash=_hash({'goal': str(goal)}),
            plan_hash=_hash(plan or {}),
            state='permitted' if context.get('trusted_action_permitted') else 'proposed',
        )
        self.active[tx.id] = tx
        if self.path is not None:
            now = tx.created_at
            with self._lock, self._con() as con:
                con.execute(
                    '''INSERT INTO operator_transactions(
                       id,owner_id,device_id,session_id,security_epoch,execution_id,conversation_id,workflow_id,
                       goal_hash,plan_hash,state,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (tx.id,tx.owner_id,tx.device_id,tx.session_id,tx.security_epoch,tx.execution_id,
                     tx.conversation_id,tx.workflow_id,tx.goal_hash,tx.plan_hash,tx.state,now,now),
                )
                authority_states = ['proposed','policy_check','approval_required','permitted'] if context.get('trusted_action_permitted') else ['proposed']
                for state in authority_states:
                    con.execute(
                        'INSERT INTO operator_state_history(transaction_id,state,reason,created_at) VALUES(?,?,?,?)',
                        (tx.id,state,'trusted_action_boundary' if state!='proposed' else 'operator_requested',now),
                    )
        return tx

    def _set_tx_state(self, tx: DesktopTransaction, state: str, *, reason=''):
        if state not in STATES:
            raise ValueError(f'invalid operator state: {state}')
        tx.state = state
        if self.path is not None:
            now = time.time()
            with self._lock, self._con() as con:
                con.execute(
                    'UPDATE operator_transactions SET state=?,updated_at=?,completed_at=CASE WHEN ? IN (\'completed\',\'failed\',\'cancelled\',\'recovery_review_required\') THEN ? ELSE completed_at END,last_error=CASE WHEN ?=\'failed\' OR ?=\'recovery_review_required\' THEN ? ELSE last_error END WHERE id=?',
                    (state,now,state,now,state,state,str(reason or '')[:500] or None,tx.id),
                )
                con.execute(
                    'INSERT INTO operator_state_history(transaction_id,state,reason,created_at) VALUES(?,?,?,?)',
                    (tx.id,state,str(reason or '')[:500],now),
                )

    def cancel(self, tx: DesktopTransaction, reason='cancelled'):
        if tx.state in TERMINAL_STATES:
            return {'cancelled': tx.state == 'cancelled', 'tx_id': tx.id, 'state': tx.state}
        self._set_tx_state(tx, 'cancelled', reason=reason)
        self.active.pop(tx.id, None)
        return {'cancelled': True, 'tx_id': tx.id, 'state': tx.state}

    def execute(self, tx: DesktopTransaction, kind: str, *, action_id=None, **params):
        if tx.state in TERMINAL_STATES:
            raise RuntimeError(f'operator transaction is terminal: {tx.state}')
        ordinal = len(tx.actions) + 1
        action_id = str(action_id or uuid.uuid4())
        ph = _hash(params)
        if self.path is not None:
            with self._lock, self._con() as con:
                existing = con.execute(
                    'SELECT * FROM operator_actions WHERE transaction_id=? AND ordinal=?',
                    (tx.id, ordinal),
                ).fetchone()
                if existing:
                    if existing['parameter_hash'] != ph or existing['kind'] != kind:
                        raise RuntimeError('operator idempotency conflict')
                    if existing['state'] == 'completed':
                        return {'result': None, 'verified': bool(existing['verified']), 'tx_id': tx.id, 'action_id': existing['id'], 'replayed': True}
                    raise RuntimeError('operator action already exists and requires recovery review')
                con.execute(
                    '''INSERT INTO operator_actions(id,transaction_id,ordinal,kind,parameter_hash,state,dispatched_at)
                       VALUES(?,?,?,?,?,'executing',?)''',
                    (action_id,tx.id,ordinal,kind,ph,time.time()),
                )
        self._set_tx_state(tx, 'executing')
        before = self.controller.snapshot()
        try:
            result = getattr(self.controller, kind)(**params)
        except Exception as exc:
            self._set_tx_state(tx, 'recovery_review_required', reason=f'{type(exc).__name__}:outcome_uncertain')
            if self.path is not None:
                with self._con() as con:
                    con.execute(
                        "UPDATE operator_actions SET state='recovery_review_required',error_type=? WHERE id=?",
                        (type(exc).__name__, action_id),
                    )
            raise
        self._set_tx_state(tx, 'verifying')
        after = self.controller.snapshot()
        undo = self.controller.undo_descriptor(kind, before, params)
        verified = bool(self.controller.verify_change(before, after, kind))
        action = DesktopAction(action_id,kind,dict(params),undo,verified,'completed' if verified else 'failed',ordinal)
        tx.actions.append(action)
        if self.path is not None:
            with self._lock, self._con() as con:
                con.execute(
                    "UPDATE operator_actions SET state=?,undo_json=?,verified=?,verified_at=? WHERE id=?",
                    ('completed' if verified else 'failed', _safe_json(undo) if undo else None, int(verified), time.time(), action_id),
                )
        if not verified:
            self._set_tx_state(tx, 'failed', reason='action_verification_failed')
        return {'result':result,'verified':verified,'tx_id':tx.id,'action_id':action_id,'replayed':False}

    def rollback(self, tx: DesktopTransaction):
        results=[]
        for action in reversed(tx.actions):
            if action.undo:
                results.append(self.controller.apply_undo(action.undo))
        if tx.state not in {'recovery_review_required','cancelled'}:
            self._set_tx_state(tx, 'failed', reason='rolled_back_after_failure')
        self.active.pop(tx.id,None)
        return results

    def commit(self, tx: DesktopTransaction):
        if any(not action.verified for action in tx.actions):
            self._set_tx_state(tx, 'failed', reason='unverified_action')
            raise RuntimeError('cannot commit an operator transaction containing unverified actions')
        tx.committed=True
        self._set_tx_state(tx, 'completed')
        self.active.pop(tx.id,None)
        return {'committed':True,'tx_id':tx.id,'state':tx.state}

    def get(self, tx_id: str):
        if self.path is None:
            return self.active.get(tx_id)
        with self._con() as con:
            row=con.execute('SELECT * FROM operator_transactions WHERE id=?',(tx_id,)).fetchone()
            return dict(row) if row else None

    def recovery_required(self):
        if self.path is None:
            return [tx for tx in self.active.values() if tx.state=='recovery_review_required']
        with self._con() as con:
            return [dict(row) for row in con.execute("SELECT * FROM operator_transactions WHERE state='recovery_review_required' ORDER BY updated_at")]
