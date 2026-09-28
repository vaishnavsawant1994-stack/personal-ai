from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from memory.second_brain import MemoryCandidate


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class OperationStoreMixin:
    OPERATION_UPDATE_FIELDS = frozenset({
        'status', 'outcome_state', 'approval_id', 'budget_run_id', 'current_step',
        'everyday_item_id', 'outcome_memory_id', 'recovery_transaction_id', 'last_error',
        'updated_at', 'completed_at',
    })
    def _init_db(self):
        self._db.execute('CREATE TABLE IF NOT EXISTS operation_plans (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
        self._db.execute(
            '''CREATE TABLE IF NOT EXISTS operation_delegations(
                operation_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                outcome_state TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                device_id TEXT,
                session_id TEXT,
                security_epoch INTEGER NOT NULL DEFAULT 0,
                idempotency_key TEXT NOT NULL UNIQUE,
                approval_id TEXT,
                budget_run_id TEXT,
                current_step INTEGER NOT NULL DEFAULT 0,
                risk_summary_json TEXT NOT NULL DEFAULT '{}',
                source_refs_json TEXT NOT NULL DEFAULT '[]',
                everyday_item_id TEXT,
                outcome_memory_id TEXT,
                recovery_transaction_id TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )'''
        )
        columns = {row['name'] for row in self._db.execute('PRAGMA table_info(operation_delegations)')}
        if 'security_epoch' not in columns:
            self._db.execute('ALTER TABLE operation_delegations ADD COLUMN security_epoch INTEGER NOT NULL DEFAULT 0')
        if 'recovery_transaction_id' not in columns:
            self._db.execute('ALTER TABLE operation_delegations ADD COLUMN recovery_transaction_id TEXT')
        self._db.execute('CREATE INDEX IF NOT EXISTS idx_operation_status ON operation_delegations(status,updated_at)')
        self._db.execute('CREATE INDEX IF NOT EXISTS idx_operation_everyday ON operation_delegations(everyday_item_id,status)')
        self._db.commit()
    def _recover_interrupted(self):
        if self._db is None:
            return
        stamp = _utc_now()
        self._db.execute(
            """UPDATE operation_delegations
                  SET status='recovery_required',outcome_state='UNCERTAIN',
                      last_error='runtime restarted while delegated execution was in progress; owner recovery review required',
                      updated_at=?
                WHERE status IN ('queued','executing','verifying')""",
            (stamp,),
        )
        self._db.commit()
    def _audit(self, action: str, payload: dict | None = None):
        if self.memory is None:
            return
        safe = {}
        for key, value in dict(payload or {}).items():
            low = str(key).lower()
            if any(marker in low for marker in ('content', 'instruction', 'parameter', 'secret', 'token', 'password', 'cookie', 'authorization')):
                continue
            safe[str(key)] = value
        try:
            self.memory.audit('personal-operations', action, safe)
        except Exception:
            pass
    def _emit(self, event: str, **payload):
        if self.events:
            self.events.emit(event, **payload)
        self._audit(event.removeprefix('future.operation.'), payload)
    def _save_plan(self, plan):
        with self._lock:
            self._plans[plan['id']] = plan
            if self._db is not None:
                self._db.execute(
                    'INSERT OR REPLACE INTO operation_plans(id,document) VALUES(?,?)',
                    (plan['id'], json.dumps(plan, sort_keys=True, default=str)),
                )
                self._db.commit()
    def plan(self, plan_id):
        return self._plans.get(plan_id)
    def _operation_id(self, plan_id: str):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f'personal-ai:p6:{plan_id}'))
    def _delegation(self, operation_id: str):
        if self._db is None:
            return None
        with self._lock:
            row = self._db.execute('SELECT * FROM operation_delegations WHERE operation_id=?', (operation_id,)).fetchone()
        return self._decode_operation(row)
    def _by_plan(self, plan_id: str):
        if self._db is None:
            return None
        with self._lock:
            row = self._db.execute('SELECT * FROM operation_delegations WHERE plan_id=?', (plan_id,)).fetchone()
        return self._decode_operation(row)
    @staticmethod
    def _decode_operation(row):
        if row is None:
            return None
        item = dict(row)
        for key in ('risk_summary_json', 'source_refs_json'):
            try:
                item[key.removesuffix('_json')] = json.loads(item.pop(key) or ('{}' if key.startswith('risk') else '[]'))
            except Exception:
                item[key.removesuffix('_json')] = {} if key.startswith('risk') else []
        return item
    def _insert_operation(self, plan, *, owner_id, device_id, session_id, security_epoch):
        operation_id = self._operation_id(plan['id'])
        existing = self._by_plan(plan['id'])
        if existing:
            return existing, False
        stamp = _utc_now()
        key = _digest({'plan_id': plan['id'], 'owner_id': owner_id, 'device_id': device_id})
        summary = self._risk_summary(plan)
        if self._db is None:
            return {
                'operation_id': operation_id, 'plan_id': plan['id'], 'status': 'queued', 'outcome_state': 'QUEUED',
                'owner_id': owner_id, 'device_id': device_id, 'session_id': session_id, 'security_epoch': int(security_epoch), 'idempotency_key': key,
                'approval_id': None, 'budget_run_id': operation_id, 'current_step': 0,
                'risk_summary': summary, 'source_refs': plan.get('source_refs', []),
                'everyday_item_id': plan.get('everyday_item_id'), 'outcome_memory_id': None, 'recovery_transaction_id': None,
                'last_error': None, 'created_at': stamp, 'updated_at': stamp, 'completed_at': None,
            }, True
        with self._lock:
            try:
                self._db.execute(
                    '''INSERT INTO operation_delegations(
                        operation_id,plan_id,status,outcome_state,owner_id,device_id,session_id,security_epoch,idempotency_key,
                        approval_id,budget_run_id,current_step,risk_summary_json,source_refs_json,everyday_item_id,
                        outcome_memory_id,recovery_transaction_id,last_error,created_at,updated_at,completed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (
                        operation_id, plan['id'], 'queued', 'QUEUED', str(owner_id or 'owner'), device_id, session_id, int(security_epoch), key,
                        None, operation_id, 0, json.dumps(summary, sort_keys=True), json.dumps(plan.get('source_refs', [])),
                        plan.get('everyday_item_id'), None, None, None, stamp, stamp, None,
                    ),
                )
                self._db.commit()
            except sqlite3.IntegrityError:
                existing = self._by_plan(plan['id'])
                if existing:
                    return existing, False
                raise
            row = self._db.execute('SELECT * FROM operation_delegations WHERE operation_id=?', (operation_id,)).fetchone()
        return self._decode_operation(row), True
    def _update_operation(self, operation_id: str, **fields):
        if self._db is None or not fields:
            return
        fields['updated_at'] = _utc_now()
        unknown = set(fields) - self.OPERATION_UPDATE_FIELDS
        if unknown:
            raise ValueError(f'invalid operation update fields: {sorted(unknown)}')
        columns = ','.join(f'{key}=?' for key in fields)
        with self._lock:
            self._db.execute(f'UPDATE operation_delegations SET {columns} WHERE operation_id=?', [*fields.values(), operation_id])
            self._db.commit()
    def _assert_owner(self, operation: dict, *, owner_id: str, device_id=None, session_id=None):
        if operation.get('owner_id') != str(owner_id or 'owner'):
            raise PermissionError('operation owner mismatch')
        if operation.get('device_id') is not None and device_id != operation.get('device_id'):
            raise PermissionError('operation device mismatch')
        if operation.get('session_id') is not None and session_id != operation.get('session_id'):
            raise PermissionError('operation session mismatch')
