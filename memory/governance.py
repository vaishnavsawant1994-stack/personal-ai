from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

from memory.policy import is_never_store
from memory.second_brain import MemoryCandidate


class GovernedMemory:
    """Owner-control gate around the canonical SecondBrain.

    This is governance, not a second memory authority. SecondBrain/MemoryStore
    remains canonical memory truth. This layer owns candidate lifecycle,
    owner-scoping, retry identity and promotion recovery.
    """

    CANONICAL_OWNER = 'owner'
    EXPLICIT_SOURCES = frozenset({
        'user', 'user-message', 'explicit-user', 'explicit-owner',
        'owner-confirmed', 'owner-import',
    })

    def __init__(self, brain, path: Path, *, events=None):
        self._brain = brain
        self.events = events
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS memory_candidates(
                    id TEXT PRIMARY KEY,
                    candidate_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_candidates_status
                    ON memory_candidates(status,created_at);
                '''
            )
            self._ensure_column(con, 'memory_candidates', 'owner_id', "TEXT NOT NULL DEFAULT 'owner'")
            self._ensure_column(con, 'memory_candidates', 'request_id', 'TEXT')
            self._ensure_column(con, 'memory_candidates', 'fingerprint', 'TEXT')
            self._ensure_column(con, 'memory_candidates', 'memory_id', 'TEXT')
            con.execute('CREATE INDEX IF NOT EXISTS idx_memory_candidates_owner_status ON memory_candidates(owner_id,status,created_at)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_memory_candidates_request ON memory_candidates(owner_id,request_id)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_memory_candidates_fingerprint ON memory_candidates(owner_id,fingerprint,status)')
        try:
            self._brain.store.second_brain = self
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._brain, name)

    @staticmethod
    def _ensure_column(con, table: str, name: str, definition: str):
        columns = {row['name'] for row in con.execute(f'PRAGMA table_info({table})')}
        if name not in columns:
            con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')

    def _con(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA busy_timeout=30000')
        return con

    @classmethod
    def _require_owner(cls, owner_id: str | None) -> str:
        owner = str(owner_id or '').strip()
        if owner != cls.CANONICAL_OWNER:
            raise PermissionError('Personal Memory is scoped to the canonical owner')
        return owner

    def _emit(self, name: str, **payload):
        if self.events:
            self.events.emit(name, **payload)

    @staticmethod
    def _normalize(candidate: MemoryCandidate) -> dict:
        return {
            'type': str(candidate.type),
            'subject': str(candidate.subject),
            'content': str(candidate.content),
            'confidence': max(0.0, min(1.0, float(candidate.confidence))),
            'source': str(candidate.source or 'unknown'),
            'verified': bool(candidate.verified),
            'tags': list(candidate.tags or []),
            'importance': max(0.0, min(1.0, float(candidate.importance))),
            'sensitivity': str(candidate.sensitivity or 'normal').strip().lower(),
            'occurred_at': candidate.occurred_at,
            'evidence': list(candidate.evidence or []),
            'metadata': dict(candidate.metadata or {}),
            'relationships': list(candidate.relationships or []),
        }

    @staticmethod
    def _fingerprint(data: dict) -> str:
        stable = {
            'type': str(data.get('type') or '').strip().lower(),
            'subject': str(data.get('subject') or '').strip().lower(),
            'content': str(data.get('content') or '').strip(),
            'source': str(data.get('source') or '').strip().lower(),
            'sensitivity': str(data.get('sensitivity') or 'normal').strip().lower(),
        }
        return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    @classmethod
    def _authoritative(cls, data: dict) -> bool:
        source = str(data.get('source') or '').strip().lower()
        return bool(data.get('verified')) and (
            source in cls.EXPLICIT_SOURCES
            or source.startswith('owner-confirmed:')
            or source.startswith('owner-import:')
        )

    @staticmethod
    def _candidate(data: dict, *, confirmed: bool = False) -> MemoryCandidate:
        source = str(data.get('source') or 'candidate')
        if confirmed:
            source = f'owner-confirmed:{source}'
        return MemoryCandidate(
            type=data['type'], subject=data['subject'], content=data['content'],
            confidence=float(data.get('confidence', 1.0)), source=source,
            verified=True if confirmed else bool(data.get('verified')),
            tags=list(data.get('tags') or []), importance=float(data.get('importance', 0.5)),
            sensitivity=str(data.get('sensitivity') or 'normal'), occurred_at=data.get('occurred_at'),
            evidence=list(data.get('evidence') or []), metadata=dict(data.get('metadata') or {}),
            relationships=list(data.get('relationships') or []),
        )

    def remember(self, candidate: MemoryCandidate, *, owner_id: str = CANONICAL_OWNER, request_id: str | None = None) -> str | None:
        owner = self._require_owner(owner_id)
        data = self._normalize(candidate)
        sensitivity = data['sensitivity']
        if is_never_store(sensitivity=sensitivity, metadata=data.get('metadata')):
            self._emit('memory.candidate.blocked', reason='never_store', source=data['source'])
            return None
        if self._authoritative(data):
            memory_id = self._brain.remember(candidate)
            self._emit('memory.committed', memory_id=memory_id, source=data['source'], verified=True)
            return memory_id
        if sensitivity != 'normal':
            self._emit('memory.candidate.blocked', reason='sensitive_requires_explicit_owner_write', source=data['source'])
            return None

        fingerprint = self._fingerprint(data)
        stamp = time.time()
        candidate_id = str(uuid.uuid4())
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            if request_id:
                existing = con.execute(
                    "SELECT * FROM memory_candidates WHERE owner_id=? AND request_id=? AND fingerprint=? ORDER BY created_at DESC LIMIT 1",
                    (owner, str(request_id), fingerprint),
                ).fetchone()
            else:
                existing = con.execute(
                    "SELECT * FROM memory_candidates WHERE owner_id=? AND fingerprint=? AND status IN ('pending','promoting','approved') ORDER BY created_at DESC LIMIT 1",
                    (owner, fingerprint),
                ).fetchone()
            if existing:
                return existing['memory_id'] if existing['status'] == 'approved' and existing['memory_id'] else existing['id']
            con.execute(
                '''INSERT INTO memory_candidates(
                    id,candidate_json,source,status,reason,created_at,updated_at,owner_id,request_id,fingerprint,memory_id)
                   VALUES(?,?,?,'pending','owner_confirmation_required',?,?,?,?,?,NULL)''',
                (candidate_id, json.dumps(data, sort_keys=True, default=str), data['source'], stamp, stamp, owner, str(request_id) if request_id else None, fingerprint),
            )
        self._emit('memory.candidate.pending', candidate_id=candidate_id, source=data['source'])
        return candidate_id

    def candidates(self, *, status: str = 'pending', limit: int = 100, owner_id: str = CANONICAL_OWNER) -> list[dict]:
        owner = self._require_owner(owner_id)
        bounded = max(1, min(int(limit), 500))
        with self._con() as con:
            rows = con.execute(
                '''SELECT id,candidate_json,source,status,reason,created_at,updated_at,owner_id,request_id,fingerprint,memory_id
                   FROM memory_candidates WHERE owner_id=? AND status=? ORDER BY created_at DESC,id DESC LIMIT ?''',
                (owner, str(status), bounded),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            candidate = json.loads(item.pop('candidate_json'))
            output.append({**item, 'candidate': candidate})
        return output

    def candidate(self, candidate_id: str, *, owner_id: str = CANONICAL_OWNER) -> dict | None:
        owner = self._require_owner(owner_id)
        with self._con() as con:
            row = con.execute('SELECT * FROM memory_candidates WHERE id=? AND owner_id=?', (str(candidate_id), owner)).fetchone()
        if not row:
            return None
        item = dict(row)
        item['candidate'] = json.loads(item.pop('candidate_json'))
        return item

    def approve_candidate(self, candidate_id: str, *, owner_id: str = CANONICAL_OWNER) -> str:
        owner = self._require_owner(owner_id)
        candidate_id = str(candidate_id)
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM memory_candidates WHERE id=? AND owner_id=?', (candidate_id, owner)).fetchone()
            if row is None:
                raise KeyError('memory candidate not found')
            if row['status'] == 'approved' and row['memory_id']:
                return row['memory_id']
            if row['status'] == 'rejected':
                raise KeyError('memory candidate was rejected')
            if row['status'] not in {'pending', 'promoting'}:
                raise KeyError('memory candidate is not approvable')
            data = json.loads(row['candidate_json'])
            if is_never_store(sensitivity=data.get('sensitivity'), metadata=data.get('metadata')):
                con.execute("UPDATE memory_candidates SET status='rejected',reason='never_store',updated_at=? WHERE id=?", (time.time(), candidate_id))
                raise PermissionError('NEVER_STORE content cannot become canonical Memory')
            con.execute("UPDATE memory_candidates SET status='promoting',updated_at=? WHERE id=?", (time.time(), candidate_id))

        memory_id = self._brain.remember(self._candidate(data, confirmed=True))
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute(
                "UPDATE memory_candidates SET status='approved',reason='owner_confirmed',memory_id=?,updated_at=? WHERE id=? AND owner_id=?",
                (memory_id, time.time(), candidate_id, owner),
            )
        self._emit('memory.candidate.approved', candidate_id=candidate_id, memory_id=memory_id)
        return memory_id

    def reject_candidate(self, candidate_id: str, *, owner_id: str = CANONICAL_OWNER) -> bool:
        owner = self._require_owner(owner_id)
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT status FROM memory_candidates WHERE id=? AND owner_id=?', (str(candidate_id), owner)).fetchone()
            if not row:
                return False
            if row['status'] == 'approved':
                return False
            con.execute(
                "UPDATE memory_candidates SET status='rejected',reason='owner_rejected',updated_at=? WHERE id=? AND owner_id=?",
                (time.time(), str(candidate_id), owner),
            )
        self._emit('memory.candidate.rejected', candidate_id=str(candidate_id))
        return True
