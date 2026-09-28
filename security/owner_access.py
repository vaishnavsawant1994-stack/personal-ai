from __future__ import annotations

import base64
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.security import hash_secret, verify_secret


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


class OwnerAccessStore:
    """Durable owner login methods without storing reusable plaintext secrets."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS owner_password(
                id INTEGER PRIMARY KEY CHECK(id=1),salt TEXT NOT NULL,password_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')
            con.execute('''CREATE TABLE IF NOT EXISTS recovery_codes(
                id TEXT PRIMARY KEY,salt TEXT NOT NULL,code_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,used_at TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS passkeys(
                credential_id BLOB PRIMARY KEY,public_key BLOB NOT NULL,sign_count INTEGER NOT NULL,
                name TEXT NOT NULL,transports TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,
                last_used_at TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS auth_challenges(
                id TEXT PRIMARY KEY,kind TEXT NOT NULL,challenge BLOB NOT NULL,device_id TEXT,
                rp_id TEXT NOT NULL,origin TEXT NOT NULL,expires_at INTEGER NOT NULL)''')

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def password_configured(self) -> bool:
        with self._con() as con:
            return con.execute('SELECT 1 FROM owner_password WHERE id=1').fetchone() is not None

    def set_password(self, password: str):
        if len(password) < 12:
            raise ValueError('Owner password must contain at least 12 characters')
        salt = secrets.token_hex(16)
        with self._con() as con:
            con.execute(
                '''INSERT INTO owner_password(id,salt,password_hash,updated_at) VALUES(1,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET salt=excluded.salt,password_hash=excluded.password_hash,
                   updated_at=excluded.updated_at''',
                (salt, hash_secret(password, salt), _now()),
            )

    def verify_password(self, password: str) -> bool:
        with self._con() as con:
            row = con.execute('SELECT salt,password_hash FROM owner_password WHERE id=1').fetchone()
        return bool(row and verify_secret(password, row['salt'], row['password_hash']))

    def regenerate_recovery_codes(self, count: int = 8) -> list[str]:
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        codes = []
        rows = []
        for _ in range(max(4, min(count, 12))):
            raw = ''.join(secrets.choice(alphabet) for _ in range(12))
            code = '-'.join(raw[index:index + 4] for index in range(0, 12, 4))
            salt = secrets.token_hex(16)
            codes.append(code)
            rows.append((str(uuid.uuid4()), salt, hash_secret(code, salt), _now()))
        with self._con() as con:
            con.execute('DELETE FROM recovery_codes')
            con.executemany(
                'INSERT INTO recovery_codes(id,salt,code_hash,created_at,used_at) VALUES(?,?,?,?,NULL)',
                rows,
            )
        return codes

    def recovery_codes_remaining(self) -> int:
        with self._con() as con:
            row = con.execute('SELECT COUNT(*) AS count FROM recovery_codes WHERE used_at IS NULL').fetchone()
        return int(row['count'])

    def consume_recovery_code(self, code: str) -> bool:
        candidate = str(code or '').strip().upper()
        with self._con() as con:
            rows = con.execute('SELECT id,salt,code_hash FROM recovery_codes WHERE used_at IS NULL').fetchall()
            for row in rows:
                if verify_secret(candidate, row['salt'], row['code_hash']):
                    con.execute('UPDATE recovery_codes SET used_at=? WHERE id=?', (_now(), row['id']))
                    return True
        return False

    def save_passkey(self, credential_id: bytes, public_key: bytes, sign_count: int, name: str, transports=''):
        with self._con() as con:
            con.execute(
                '''INSERT INTO passkeys(credential_id,public_key,sign_count,name,transports,created_at,last_used_at)
                   VALUES(?,?,?,?,?,?,NULL)
                   ON CONFLICT(credential_id) DO UPDATE SET public_key=excluded.public_key,
                   sign_count=excluded.sign_count,name=excluded.name,transports=excluded.transports''',
                (credential_id, public_key, int(sign_count), str(name or 'Owner passkey')[:120], str(transports), _now()),
            )

    def passkeys(self) -> list[dict]:
        with self._con() as con:
            rows = con.execute(
                'SELECT credential_id,name,transports,created_at,last_used_at FROM passkeys ORDER BY created_at'
            ).fetchall()
        return [
            {
                'credential_id': _encode(bytes(row['credential_id'])),
                'name': row['name'],
                'transports': row['transports'],
                'created_at': row['created_at'],
                'last_used_at': row['last_used_at'],
            }
            for row in rows
        ]

    def passkey(self, credential_id: bytes):
        with self._con() as con:
            row = con.execute('SELECT * FROM passkeys WHERE credential_id=?', (credential_id,)).fetchone()
        return dict(row) if row else None

    def use_passkey(self, credential_id: bytes, sign_count: int):
        with self._con() as con:
            con.execute(
                'UPDATE passkeys SET sign_count=?,last_used_at=? WHERE credential_id=?',
                (int(sign_count), _now(), credential_id),
            )

    def create_challenge(self, kind: str, challenge: bytes, rp_id: str, origin: str, *, device_id=None, ttl=180):
        challenge_id = str(uuid.uuid4())
        expires_at = int(datetime.now(timezone.utc).timestamp()) + max(30, min(int(ttl), 300))
        with self._con() as con:
            con.execute('DELETE FROM auth_challenges WHERE expires_at<?', (int(datetime.now(timezone.utc).timestamp()),))
            con.execute(
                'INSERT INTO auth_challenges VALUES(?,?,?,?,?,?,?)',
                (challenge_id, kind, challenge, device_id, rp_id, origin, expires_at),
            )
        return challenge_id

    def consume_challenge(self, challenge_id: str, kind: str, *, device_id=None):
        with self._con() as con:
            row = con.execute('SELECT * FROM auth_challenges WHERE id=?', (challenge_id,)).fetchone()
            con.execute('DELETE FROM auth_challenges WHERE id=?', (challenge_id,))
        if not row or row['kind'] != kind:
            return None
        if int(row['expires_at']) < int(datetime.now(timezone.utc).timestamp()):
            return None
        if row['device_id'] is not None and row['device_id'] != device_id:
            return None
        return dict(row)
