from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from typing import Any


def parameter_hash(parameters: dict[str, Any]) -> str:
    raw = json.dumps(
        parameters or {},
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        default=str,
    ).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ApprovalTicket:
    id: str
    execution_id: str
    tool_name: str
    parameter_hash: str
    created_at: float
    expires_at: float
    owner_id: str = 'owner'
    device_id: str | None = None
    session_id: str | None = None
    security_epoch: int = 0
    destination: str = ''
    data_classification: str = 'internal'
    max_uses: int = 1


class ApprovalManager:
    """Canonical durable approval authority.

    Production instances use the shared trusted-actions SQLite database. Approval
    decisions, dispatch ownership and terminal results are persisted so a router
    restart cannot erase or duplicate a governed operation. The in-memory mode
    remains only for isolated legacy tests that do not provide ``path``.
    """

    ACTIVE_STATUSES = frozenset({'pending', 'approved', 'dispatching', 'recovery_required'})
    TERMINAL_STATUSES = frozenset({'completed', 'rejected', 'expired', 'invalidated', 'cancelled', 'consumed'})

    def __init__(self, ttl_seconds: int = 300, *, path: Path | None = None):
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self._tickets: dict[str, tuple[ApprovalTicket, str]] = {}
        self._contexts: dict[str, dict] = {}
        self._outcomes: dict[str, dict] = {}
        self._epoch = 0
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    def _con(self):
        if self.path is None:
            raise RuntimeError('durable approval database is not configured')
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self):
        with self._con() as con:
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS approval_tickets(
                    id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    parameter_hash TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    device_id TEXT,
                    session_id TEXT,
                    security_epoch INTEGER NOT NULL,
                    destination TEXT NOT NULL DEFAULT '',
                    data_classification TEXT NOT NULL DEFAULT 'internal',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    max_uses INTEGER NOT NULL DEFAULT 1,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    consumed_at REAL,
                    rejected_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_approval_status_expiry
                    ON approval_tickets(status,expires_at);
                CREATE TABLE IF NOT EXISTS approval_continuations(
                    approval_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(approval_id) REFERENCES approval_tickets(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS approval_security_state(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                INSERT OR IGNORE INTO approval_security_state(key,value,updated_at)
                    VALUES('security_epoch','0',0);
                '''
            )
            cols = {row[1] for row in con.execute('PRAGMA table_info(approval_tickets)')}
            additions = {
                'decided_at': 'REAL',
                'dispatch_started_at': 'REAL',
                'completed_at': 'REAL',
                'outcome_json': 'TEXT',
                'failure_code': 'TEXT',
                'dispatch_owner': 'TEXT',
                'dispatch_lease_expires_at': 'REAL',
            }
            for name, kind in additions.items():
                if name not in cols:
                    con.execute(f'ALTER TABLE approval_tickets ADD COLUMN {name} {kind}')

    @staticmethod
    def _from_row(row) -> ApprovalTicket:
        return ApprovalTicket(
            id=row['id'],
            execution_id=row['execution_id'],
            tool_name=row['tool_name'],
            parameter_hash=row['parameter_hash'],
            created_at=float(row['created_at']),
            expires_at=float(row['expires_at']),
            owner_id=row['owner_id'],
            device_id=row['device_id'],
            session_id=row['session_id'],
            security_epoch=int(row['security_epoch']),
            destination=row['destination'] or '',
            data_classification=row['data_classification'] or 'internal',
            max_uses=int(row['max_uses']),
        )

    @staticmethod
    def _safe_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(',', ':'))

    def current_security_epoch(self) -> int:
        if self.path is None:
            with self._lock:
                return self._epoch
        with self._con() as con:
            row = con.execute(
                "SELECT value FROM approval_security_state WHERE key='security_epoch'"
            ).fetchone()
        return int(row['value']) if row else 0

    def advance_security_epoch(self) -> int:
        """Invalidate approvals not yet dispatched and fence uncertain dispatches."""
        if self.path is None:
            with self._lock:
                self._epoch += 1
                updated = {}
                for key, (ticket, status) in self._tickets.items():
                    if status in {'pending', 'approved'}:
                        status = 'invalidated'
                    elif status == 'dispatching':
                        status = 'recovery_required'
                    updated[key] = (ticket, status)
                self._tickets = updated
                return self._epoch
        now = time.time()
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute(
                "SELECT value FROM approval_security_state WHERE key='security_epoch'"
            ).fetchone()
            epoch = (int(row['value']) if row else 0) + 1
            con.execute(
                "INSERT INTO approval_security_state(key,value,updated_at) VALUES('security_epoch',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (str(epoch), now),
            )
            con.execute(
                "UPDATE approval_tickets SET status='invalidated',failure_code='security_epoch_changed' "
                "WHERE status IN ('pending','approved')"
            )
            con.execute(
                "UPDATE approval_tickets SET status='recovery_required',failure_code='security_epoch_changed_during_dispatch' "
                "WHERE status='dispatching'"
            )
            con.commit()
        return epoch

    def create(
        self,
        execution_id: str,
        tool_name: str,
        parameters: dict[str, Any],
        *,
        owner_id: str = 'owner',
        device_id: str | None = None,
        session_id: str | None = None,
        security_epoch: int | None = None,
        destination: str = '',
        data_classification: str = 'internal',
    ) -> ApprovalTicket:
        now = time.time()
        epoch = self.current_security_epoch() if security_epoch is None else int(security_epoch)
        ticket = ApprovalTicket(
            secrets.token_urlsafe(24),
            str(execution_id),
            str(tool_name),
            parameter_hash(parameters),
            now,
            now + self.ttl_seconds,
            str(owner_id or 'owner'),
            str(device_id) if device_id else None,
            str(session_id) if session_id else None,
            epoch,
            str(destination or '')[:1000],
            str(data_classification or 'internal')[:40],
            1,
        )
        if self.path is None:
            with self._lock:
                self._tickets[ticket.id] = (ticket, 'pending')
            return ticket
        with self._lock, self._con() as con:
            con.execute(
                '''INSERT INTO approval_tickets(
                    id,execution_id,tool_name,parameter_hash,owner_id,device_id,session_id,
                    security_epoch,destination,data_classification,created_at,expires_at,max_uses,
                    used_count,status,consumed_at,rejected_at,decided_at,dispatch_started_at,
                    completed_at,outcome_json,failure_code)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,0,'pending',NULL,NULL,NULL,NULL,NULL,NULL,NULL)''',
                (
                    ticket.id, ticket.execution_id, ticket.tool_name, ticket.parameter_hash,
                    ticket.owner_id, ticket.device_id, ticket.session_id, ticket.security_epoch,
                    ticket.destination, ticket.data_classification, ticket.created_at, ticket.expires_at,
                ),
            )
        return ticket

    @staticmethod
    def _validate_scope(
        ticket: ApprovalTicket,
        *,
        execution_id: str,
        tool_name: str,
        parameters: dict[str, Any],
        owner_id: str | None,
        device_id: str | None,
        session_id: str | None,
        security_epoch: int,
        destination: str | None,
        data_classification: str | None,
    ) -> None:
        if ticket.execution_id != execution_id or ticket.tool_name != tool_name:
            raise PermissionError('approval scope mismatch')
        if ticket.parameter_hash != parameter_hash(parameters):
            raise PermissionError('approval scope mismatch')
        if ticket.owner_id and owner_id is not None and ticket.owner_id != owner_id:
            raise PermissionError('approval owner mismatch')
        if ticket.device_id is not None and ticket.device_id != device_id:
            raise PermissionError('approval device mismatch')
        if ticket.session_id is not None and ticket.session_id != session_id:
            raise PermissionError('approval session mismatch')
        if ticket.security_epoch != int(security_epoch):
            raise PermissionError('approval security epoch mismatch')
        if destination is not None and ticket.destination != str(destination or '')[:1000]:
            raise PermissionError('approval destination mismatch')
        if data_classification is not None and ticket.data_classification != str(data_classification or 'internal')[:40]:
            raise PermissionError('approval data classification mismatch')

    def record(self, ticket_id: str) -> dict | None:
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item:
                    return None
                ticket, status = item
                outcome = self._outcomes.get(ticket_id)
                return {'ticket': ticket, 'status': status, 'outcome': dict(outcome) if outcome else None}
        with self._con() as con:
            row = con.execute('SELECT * FROM approval_tickets WHERE id=?', (ticket_id,)).fetchone()
        if not row:
            return None
        outcome = json.loads(row['outcome_json']) if row['outcome_json'] else None
        return {
            'ticket': self._from_row(row),
            'status': row['status'],
            'outcome': outcome,
            'failure_code': row['failure_code'],
            'decided_at': row['decided_at'],
            'dispatch_started_at': row['dispatch_started_at'],
            'completed_at': row['completed_at'],
            'dispatch_owner': row['dispatch_owner'],
            'dispatch_lease_expires_at': row['dispatch_lease_expires_at'],
        }

    def approve(
        self,
        ticket_id: str,
        execution_id: str,
        tool_name: str,
        parameters: dict[str, Any],
        *,
        now: float | None = None,
        owner_id: str | None = None,
        device_id: str | None = None,
        session_id: str | None = None,
        security_epoch: int | None = None,
        destination: str | None = None,
        data_classification: str | None = None,
    ) -> dict:
        """Persist one owner decision without dispatching the operation."""
        now = time.time() if now is None else float(now)
        epoch = self.current_security_epoch() if security_epoch is None else int(security_epoch)
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item:
                    raise PermissionError('approval is missing')
                ticket, status = item
                if status in {'rejected', 'expired', 'invalidated', 'cancelled', 'consumed'}:
                    raise PermissionError(f'approval is {status}')
                if status == 'pending' and now >= ticket.expires_at:
                    self._tickets[ticket_id] = (ticket, 'expired')
                    raise PermissionError('approval expired')
                self._validate_scope(
                    ticket, execution_id=execution_id, tool_name=tool_name, parameters=parameters,
                    owner_id=owner_id, device_id=device_id, session_id=session_id,
                    security_epoch=epoch, destination=destination,
                    data_classification=data_classification,
                )
                if status == 'pending':
                    status = 'approved'
                    self._tickets[ticket_id] = (ticket, status)
                return {'ticket': ticket, 'status': status, 'outcome': self._outcomes.get(ticket_id)}
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM approval_tickets WHERE id=?', (ticket_id,)).fetchone()
            if not row:
                con.rollback()
                raise PermissionError('approval is missing')
            ticket = self._from_row(row)
            status = str(row['status'])
            if status in {'rejected', 'expired', 'invalidated', 'cancelled', 'consumed'}:
                con.rollback()
                raise PermissionError(f'approval is {status}')
            if status == 'pending' and now >= ticket.expires_at:
                con.execute(
                    "UPDATE approval_tickets SET status='expired',failure_code='expired' WHERE id=? AND status='pending'",
                    (ticket_id,),
                )
                con.commit()
                raise PermissionError('approval expired')
            self._validate_scope(
                ticket, execution_id=execution_id, tool_name=tool_name, parameters=parameters,
                owner_id=owner_id, device_id=device_id, session_id=session_id,
                security_epoch=epoch, destination=destination,
                data_classification=data_classification,
            )
            if status == 'pending':
                cur = con.execute(
                    "UPDATE approval_tickets SET status='approved',decided_at=?,used_count=1 WHERE id=? AND status='pending' AND used_count=0",
                    (now, ticket_id),
                )
                if cur.rowcount != 1:
                    con.rollback()
                    raise PermissionError('approval decision raced; retry canonical approval')
                status = 'approved'
            outcome = json.loads(row['outcome_json']) if row['outcome_json'] else None
            con.commit()
            return {'ticket': ticket, 'status': status, 'outcome': outcome}

    def begin_dispatch(
        self,
        ticket_id: str,
        *,
        now: float | None = None,
        worker_id: str = '',
        lease_seconds: int = 30,
    ) -> dict:
        """Atomically grant dispatch ownership to exactly one runtime."""
        now = time.time() if now is None else float(now)
        worker_id = str(worker_id or '')[:160]
        lease_expires = now + max(5, min(int(lease_seconds), 300))
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item:
                    raise PermissionError('approval is missing')
                ticket, status = item
                if status == 'approved' and now >= ticket.expires_at:
                    self._tickets[ticket_id] = (ticket, 'expired')
                    raise PermissionError('approval expired before dispatch')
                if status == 'approved':
                    self._tickets[ticket_id] = (ticket, 'dispatching')
                    return {'dispatch': True, 'status': 'dispatching', 'ticket': ticket, 'outcome': None}
                return {'dispatch': False, 'status': status, 'ticket': ticket, 'outcome': self._outcomes.get(ticket_id)}
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM approval_tickets WHERE id=?', (ticket_id,)).fetchone()
            if not row:
                con.rollback()
                raise PermissionError('approval is missing')
            ticket = self._from_row(row)
            status = str(row['status'])
            if status == 'approved' and now >= ticket.expires_at:
                con.execute(
                    "UPDATE approval_tickets SET status='expired',failure_code='expired_before_dispatch' WHERE id=? AND status='approved'",
                    (ticket_id,),
                )
                con.commit()
                raise PermissionError('approval expired before dispatch')
            if status == 'approved':
                cur = con.execute(
                    "UPDATE approval_tickets SET status='dispatching',dispatch_started_at=?,dispatch_owner=?,dispatch_lease_expires_at=? WHERE id=? AND status='approved'",
                    (now, worker_id, lease_expires, ticket_id),
                )
                if cur.rowcount == 1:
                    con.commit()
                    return {'dispatch': True, 'status': 'dispatching', 'ticket': ticket, 'outcome': None}
                row = con.execute('SELECT * FROM approval_tickets WHERE id=?', (ticket_id,)).fetchone()
                status = str(row['status'])
            if status == 'dispatching':
                lease_deadline = row['dispatch_lease_expires_at']
                if lease_deadline is not None and float(lease_deadline) <= now:
                    con.execute(
                        "UPDATE approval_tickets SET status='recovery_required',failure_code='dispatch_lease_expired' WHERE id=? AND status='dispatching'",
                        (ticket_id,),
                    )
                    status = 'recovery_required'
            outcome = json.loads(row['outcome_json']) if row['outcome_json'] else None
            con.commit()
            return {'dispatch': False, 'status': status, 'ticket': ticket, 'outcome': outcome}

    def complete_dispatch(self, ticket_id: str, outcome: dict, *, now: float | None = None) -> dict:
        now = time.time() if now is None else float(now)
        safe = self._safe_json(outcome or {})
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item:
                    raise PermissionError('approval is missing')
                ticket, status = item
                if status == 'completed':
                    return dict(self._outcomes.get(ticket_id) or {})
                if status != 'dispatching':
                    raise PermissionError(f'approval dispatch is {status}')
                self._tickets[ticket_id] = (ticket, 'completed')
                self._outcomes[ticket_id] = json.loads(safe)
                self._contexts.pop(ticket_id, None)
                return dict(self._outcomes[ticket_id])
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT status,outcome_json FROM approval_tickets WHERE id=?', (ticket_id,)).fetchone()
            if not row:
                con.rollback()
                raise PermissionError('approval is missing')
            if row['status'] == 'completed':
                con.rollback()
                return json.loads(row['outcome_json'] or '{}')
            cur = con.execute(
                "UPDATE approval_tickets SET status='completed',completed_at=?,outcome_json=?,failure_code=NULL WHERE id=? AND status='dispatching'",
                (now, safe, ticket_id),
            )
            if cur.rowcount != 1:
                con.rollback()
                raise PermissionError(f"approval dispatch is {row['status']}")
            con.execute('DELETE FROM approval_continuations WHERE approval_id=?', (ticket_id,))
            con.commit()
        return json.loads(safe)

    def mark_recovery_required(self, ticket_id: str, code: str = 'dispatch_outcome_uncertain') -> bool:
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item:
                    return False
                ticket, status = item
                if status == 'dispatching':
                    self._tickets[ticket_id] = (ticket, 'recovery_required')
                    return True
                return status == 'recovery_required'
        with self._lock, self._con() as con:
            cur = con.execute(
                "UPDATE approval_tickets SET status='recovery_required',failure_code=? WHERE id=? AND status='dispatching'",
                (str(code)[:120], ticket_id),
            )
            if cur.rowcount:
                return True
            row = con.execute('SELECT status FROM approval_tickets WHERE id=?', (ticket_id,)).fetchone()
            return bool(row and row['status'] == 'recovery_required')

    def invalidate(self, ticket_id: str, code: str = 'security_revalidation_failed') -> bool:
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item:
                    return False
                ticket, status = item
                if status in {'pending', 'approved'}:
                    self._tickets[ticket_id] = (ticket, 'invalidated')
                    return True
                return status == 'invalidated'
        with self._lock, self._con() as con:
            cur = con.execute(
                "UPDATE approval_tickets SET status='invalidated',failure_code=? WHERE id=? AND status IN ('pending','approved')",
                (str(code)[:120], ticket_id),
            )
            return cur.rowcount == 1

    def consume(self, ticket_id: str, execution_id: str, tool_name: str, parameters: dict[str, Any], **kwargs) -> ApprovalTicket:
        """Legacy one-use API retained for compatibility tests and non-V1 callers."""
        decided = self.approve(ticket_id, execution_id, tool_name, parameters, **kwargs)
        ticket = decided['ticket']
        now = kwargs.get('now')
        now = time.time() if now is None else float(now)
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item or item[1] != 'approved':
                    raise PermissionError('approval is missing, expired, rejected, or already used')
                self._tickets[ticket_id] = (ticket, 'consumed')
                self._contexts.pop(ticket_id, None)
                return ticket
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            cur = con.execute(
                "UPDATE approval_tickets SET status='consumed',consumed_at=? WHERE id=? AND status='approved'",
                (now, ticket_id),
            )
            if cur.rowcount != 1:
                con.rollback()
                raise PermissionError('approval is missing, expired, rejected, or already used')
            con.execute('DELETE FROM approval_continuations WHERE approval_id=?', (ticket_id,))
            con.commit()
        return ticket

    def reject(self, ticket_id: str, *, device_id: str | None = None, session_id: str | None = None, now: float | None = None) -> bool:
        now = time.time() if now is None else float(now)
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item:
                    return False
                ticket, status = item
                if ticket.device_id is not None and ticket.device_id != device_id:
                    raise PermissionError('approval device mismatch')
                if ticket.session_id is not None and ticket.session_id != session_id:
                    raise PermissionError('approval session mismatch')
                if status == 'rejected':
                    return True
                if status != 'pending':
                    return False
                self._tickets[ticket_id] = (ticket, 'rejected')
                self._contexts.pop(ticket_id, None)
                return True
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM approval_tickets WHERE id=?', (ticket_id,)).fetchone()
            if not row:
                con.rollback()
                return False
            ticket = self._from_row(row)
            if ticket.device_id is not None and ticket.device_id != device_id:
                con.rollback()
                raise PermissionError('approval device mismatch')
            if ticket.session_id is not None and ticket.session_id != session_id:
                con.rollback()
                raise PermissionError('approval session mismatch')
            if row['status'] == 'rejected':
                con.rollback()
                return True
            if row['status'] != 'pending':
                con.rollback()
                return False
            con.execute(
                "UPDATE approval_tickets SET status='rejected',rejected_at=?,decided_at=? WHERE id=? AND status='pending'",
                (now, now, ticket_id),
            )
            con.execute('DELETE FROM approval_continuations WHERE approval_id=?', (ticket_id,))
            con.commit()
            return True

    def save_context(self, ticket_id: str, payload: dict) -> None:
        safe = self._safe_json(payload)
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item or item[1] != 'pending':
                    raise PermissionError('approval is not pending')
                self._contexts[ticket_id] = json.loads(safe)
            return
        with self._lock, self._con() as con:
            pending = con.execute(
                "SELECT 1 FROM approval_tickets WHERE id=? AND status='pending'", (ticket_id,)
            ).fetchone()
            if not pending:
                raise PermissionError('approval is not pending')
            con.execute(
                '''INSERT INTO approval_continuations(approval_id,payload_json,created_at)
                   VALUES(?,?,?) ON CONFLICT(approval_id) DO UPDATE SET
                   payload_json=excluded.payload_json,created_at=excluded.created_at''',
                (ticket_id, safe, time.time()),
            )

    def context(self, ticket_id: str) -> dict | None:
        if self.path is None:
            with self._lock:
                item = self._tickets.get(ticket_id)
                if not item or item[1] not in self.ACTIVE_STATUSES:
                    return None
                value = self._contexts.get(ticket_id)
                return dict(value) if value is not None else None
        with self._con() as con:
            row = con.execute(
                '''SELECT c.payload_json FROM approval_continuations c
                   JOIN approval_tickets t ON t.id=c.approval_id
                   WHERE c.approval_id=? AND t.status IN ('pending','approved','dispatching','recovery_required')''',
                (ticket_id,),
            ).fetchone()
        return json.loads(row['payload_json']) if row else None

    def ticket(self, ticket_id: str) -> ApprovalTicket | None:
        rec = self.record(ticket_id)
        if not rec or rec['status'] != 'pending':
            return None
        ticket = rec['ticket']
        if time.time() >= ticket.expires_at:
            self.purge_expired()
            return None
        return ticket

    def list_pending(self, *, owner_id: str = 'owner', device_id: str | None = None, session_id: str | None = None) -> list[dict]:
        self.purge_expired()
        if self.path is None:
            with self._lock:
                rows = []
                for _, (ticket, status) in self._tickets.items():
                    if status != 'pending' or ticket.owner_id != owner_id:
                        continue
                    if device_id is not None and ticket.device_id not in (None, device_id):
                        continue
                    if session_id is not None and ticket.session_id not in (None, session_id):
                        continue
                    rows.append(self._safe_projection(ticket, status))
                return sorted(rows, key=lambda x: x['created_at'])
        sql = "SELECT * FROM approval_tickets WHERE status='pending' AND owner_id=? AND expires_at>?"
        args: list[Any] = [owner_id, time.time()]
        if device_id is not None:
            sql += " AND (device_id IS NULL OR device_id=?)"
            args.append(device_id)
        if session_id is not None:
            sql += " AND (session_id IS NULL OR session_id=?)"
            args.append(session_id)
        sql += ' ORDER BY created_at ASC'
        with self._con() as con:
            rows = con.execute(sql, args).fetchall()
        return [self._safe_projection(self._from_row(row), row['status']) for row in rows]

    @staticmethod
    def _safe_projection(ticket: ApprovalTicket, status: str) -> dict:
        return {
            'approval_id': ticket.id,
            'status': status,
            'action': ticket.tool_name,
            'created_at': ticket.created_at,
            'expires_at': ticket.expires_at,
            'execution_id': ticket.execution_id,
            'device_id': ticket.device_id,
            'session_id': ticket.session_id,
            'security_epoch': ticket.security_epoch,
            'destination': ticket.destination[:200],
            'data_classification': ticket.data_classification,
        }

    def purge_expired(self, *, now: float | None = None) -> int:
        now = time.time() if now is None else float(now)
        if self.path is None:
            with self._lock:
                stale = [
                    key for key, (ticket, status) in self._tickets.items()
                    if status in {'pending', 'approved'} and now >= ticket.expires_at
                ]
                for key in stale:
                    ticket = self._tickets[key][0]
                    self._tickets[key] = (ticket, 'expired')
                    self._contexts.pop(key, None)
                return len(stale)
        with self._lock, self._con() as con:
            rows = con.execute(
                "SELECT id FROM approval_tickets WHERE status IN ('pending','approved') AND expires_at<=?",
                (now,),
            ).fetchall()
            ids = [row['id'] for row in rows]
            if ids:
                placeholders = ','.join('?' for _ in ids)
                con.execute(
                    f"UPDATE approval_tickets SET status='expired',failure_code='expired' WHERE id IN ({placeholders})",
                    ids,
                )
                con.execute(
                    f"DELETE FROM approval_continuations WHERE approval_id IN ({placeholders})", ids,
                )
            return len(ids)
