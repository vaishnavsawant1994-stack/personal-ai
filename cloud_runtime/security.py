from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


DEFAULT_SCOPES = ('ai:chat', 'status:read', 'memory:read', 'approval:read', 'approval:write')


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _now() -> int:
    return int(time.time())


@dataclass(frozen=True)
class Session:
    id: str
    device_id: str
    scopes: tuple[str, ...]
    expires_at: int
    reauthenticated_at: int | None = None


class CloudSessionStore:
    """Opaque, hashed, revocable short-lived sessions. Raw tokens are never persisted."""

    def __init__(self, path: Path, ttl_seconds: int = 900):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.lock = RLock()
        with self._con() as con:
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS cloud_sessions(
                  id TEXT PRIMARY KEY,device_id TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,
                  scopes TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
                  revoked INTEGER NOT NULL DEFAULT 0,last_seen_at INTEGER,reauthenticated_at INTEGER);
                CREATE TABLE IF NOT EXISTS cloud_nonces(
                  session_id TEXT NOT NULL,nonce_hash TEXT NOT NULL,seen_at INTEGER NOT NULL,
                  PRIMARY KEY(session_id,nonce_hash));
                CREATE TABLE IF NOT EXISTS cloud_state(
                  key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at INTEGER NOT NULL);
                '''
            )
            columns = {row['name'] for row in con.execute('PRAGMA table_info(cloud_sessions)')}
            if 'reauthenticated_at' not in columns:
                con.execute('ALTER TABLE cloud_sessions ADD COLUMN reauthenticated_at INTEGER')

    def _con(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _session(row) -> Session:
        return Session(
            row['id'],
            row['device_id'],
            tuple(row['scopes'].split()),
            int(row['expires_at']),
            int(row['reauthenticated_at']) if row['reauthenticated_at'] is not None else None,
        )

    def issue(self, device_id: str, scopes=DEFAULT_SCOPES):
        token = secrets.token_urlsafe(48)
        session_id = str(uuid.uuid4())
        stamp = _now()
        expires = stamp + self.ttl_seconds
        scope_string = ' '.join(sorted(set(scopes)))
        with self.lock, self._con() as con:
            con.execute(
                '''INSERT INTO cloud_sessions(
                    id,device_id,token_hash,scopes,created_at,expires_at,revoked,last_seen_at,reauthenticated_at
                   ) VALUES(?,?,?,?,?,?,0,NULL,NULL)''',
                (session_id, device_id, _hash(token), scope_string, stamp, expires),
            )
        return token, Session(session_id, device_id, tuple(scope_string.split()), expires, None)

    def authenticate(self, token: str, required_scope: str | None = None) -> Session | None:
        if not token:
            return None
        stamp = _now()
        digest = _hash(token)
        with self.lock, self._con() as con:
            row = con.execute('SELECT * FROM cloud_sessions WHERE token_hash=?', (digest,)).fetchone()
            if not row or row['revoked'] or row['expires_at'] <= stamp:
                return None
            scopes = tuple(row['scopes'].split())
            if required_scope and required_scope not in scopes:
                return None
            con.execute('UPDATE cloud_sessions SET last_seen_at=? WHERE id=?', (stamp, row['id']))
            return Session(
                row['id'],
                row['device_id'],
                scopes,
                int(row['expires_at']),
                int(row['reauthenticated_at']) if row['reauthenticated_at'] is not None else None,
            )

    def session(self, session_id: str) -> Session | None:
        stamp = _now()
        with self._con() as con:
            row = con.execute(
                'SELECT * FROM cloud_sessions WHERE id=? AND revoked=0 AND expires_at>?',
                (session_id, stamp),
            ).fetchone()
        return self._session(row) if row else None

    def mark_reauthenticated(self, session_id: str, *, at: int | None = None) -> Session | None:
        stamp = _now() if at is None else int(at)
        with self.lock, self._con() as con:
            cur = con.execute(
                '''UPDATE cloud_sessions SET reauthenticated_at=?
                   WHERE id=? AND revoked=0 AND expires_at>?''',
                (stamp, session_id, _now()),
            )
        return self.session(session_id) if cur.rowcount == 1 else None

    def revoke(self, session_id: str) -> bool:
        with self.lock, self._con() as con:
            return con.execute(
                'UPDATE cloud_sessions SET revoked=1 WHERE id=? AND revoked=0',
                (session_id,),
            ).rowcount == 1

    def revoke_device(self, device_id: str) -> int:
        with self.lock, self._con() as con:
            return con.execute(
                'UPDATE cloud_sessions SET revoked=1 WHERE device_id=? AND revoked=0',
                (device_id,),
            ).rowcount

    def accept_nonce(self, session_id: str, nonce: str, max_age_seconds: int = 600) -> bool:
        if not nonce or len(nonce) < 16 or len(nonce) > 256:
            return False
        stamp = _now()
        digest = _hash(nonce)
        with self.lock, self._con() as con:
            con.execute('DELETE FROM cloud_nonces WHERE seen_at<?', (stamp - max_age_seconds,))
            try:
                con.execute('INSERT INTO cloud_nonces VALUES(?,?,?)', (session_id, digest, stamp))
                return True
            except sqlite3.IntegrityError:
                return False

    def set_emergency_stop(self, enabled: bool):
        with self.lock, self._con() as con:
            con.execute(
                "INSERT INTO cloud_state(key,value,updated_at) VALUES('emergency_stop',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                ('1' if enabled else '0', _now()),
            )

    def emergency_stopped(self) -> bool:
        with self._con() as con:
            row = con.execute("SELECT value FROM cloud_state WHERE key='emergency_stop'").fetchone()
            return bool(row and row['value'] == '1')


class OwnerAuthenticator:
    """Constant-time validation for a deployment-supplied owner bootstrap secret."""

    def __init__(self, secret: str):
        self._secret = (secret or '').strip()

    @property
    def configured(self) -> bool:
        return len(self._secret) >= 32

    def verify(self, candidate: str) -> bool:
        return self.configured and hmac.compare_digest(self._secret, (candidate or '').strip())
