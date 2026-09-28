from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from security.projection_redaction import sanitize_sensitive_text


REDACTED = '[REDACTED]'
SENSITIVE_KEY_PARTS = (
    'password', 'passwd', 'secret', 'token', 'authorization', 'cookie', 'credential',
    'api_key', 'apikey', 'private_key', 'root_key', 'signing_key', 'recovery_code',
    'session_id', 'sessionid', 'session_cookie',
)


def redact_audit_value(value: Any, key: str = '') -> Any:
    lowered = str(key or '').lower()
    if any(part in lowered for part in SENSITIVE_KEY_PARTS):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): redact_audit_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_audit_value(item) for item in value]
    if isinstance(value, bytes):
        return f'<bytes:{len(value)}>'
    text = str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
    if isinstance(text, str):
        sanitized = sanitize_sensitive_text(text)
        if sanitized != text:
            return sanitized
    return text


class TrustedActionAudit:
    """Redacted append-only hash chain for consequential Personal AI actions."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.anchor_path = self.path.with_suffix(self.path.suffix + '.anchor')
        self.lock = threading.RLock()
        with self._con() as con:
            con.execute(
                '''CREATE TABLE IF NOT EXISTS action_audit(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL UNIQUE
                )'''
            )

    def _con(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _canonical(*, event_id: str, category: str, action: str, payload: dict, created_at: float, prev_hash: str) -> bytes:
        return json.dumps(
            {
                'id': event_id,
                'category': category,
                'action': action,
                'payload': payload,
                'created_at': created_at,
                'prev_hash': prev_hash,
            },
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
            default=str,
        ).encode('utf-8')

    def _write_anchor(self, entry_hash: str) -> None:
        temp = self.anchor_path.with_name(f'.{self.anchor_path.name}.{secrets.token_hex(6)}.tmp')
        try:
            with temp.open('w', encoding='utf-8') as handle:
                handle.write(entry_hash)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.anchor_path)
        finally:
            temp.unlink(missing_ok=True)

    def append(self, category: str, action: str, payload: dict | None = None) -> str:
        safe_payload = redact_audit_value(payload or {})
        event_id = secrets.token_hex(16)
        created_at = time.time()
        with self.lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT entry_hash FROM action_audit ORDER BY sequence DESC LIMIT 1').fetchone()
            prev_hash = row['entry_hash'] if row else '0' * 64
            canonical = self._canonical(
                event_id=event_id,
                category=str(category),
                action=str(action),
                payload=safe_payload,
                created_at=created_at,
                prev_hash=prev_hash,
            )
            entry_hash = hashlib.sha256(canonical).hexdigest()
            con.execute(
                '''INSERT INTO action_audit(id,category,action,payload_json,created_at,prev_hash,entry_hash)
                   VALUES(?,?,?,?,?,?,?)''',
                (
                    event_id,
                    str(category),
                    str(action),
                    json.dumps(safe_payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str),
                    created_at,
                    prev_hash,
                    entry_hash,
                ),
            )
            con.commit()
            self._write_anchor(entry_hash)
        return event_id

    def entries(self, limit: int = 200) -> list[dict]:
        with self._con() as con:
            rows = con.execute(
                'SELECT * FROM action_audit ORDER BY sequence DESC LIMIT ?',
                (max(1, min(int(limit), 5000)),),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item['payload'] = json.loads(item.pop('payload_json'))
            output.append(item)
        return output

    def verify_chain(self) -> dict:
        with self._con() as con:
            rows = con.execute('SELECT * FROM action_audit ORDER BY sequence').fetchall()
        expected_prev = '0' * 64
        last_hash = expected_prev
        for row in rows:
            payload = json.loads(row['payload_json'])
            if row['prev_hash'] != expected_prev:
                return {'ok': False, 'reason': 'previous hash mismatch', 'sequence': row['sequence']}
            calculated = hashlib.sha256(
                self._canonical(
                    event_id=row['id'],
                    category=row['category'],
                    action=row['action'],
                    payload=payload,
                    created_at=float(row['created_at']),
                    prev_hash=row['prev_hash'],
                )
            ).hexdigest()
            if calculated != row['entry_hash']:
                return {'ok': False, 'reason': 'entry hash mismatch', 'sequence': row['sequence']}
            expected_prev = row['entry_hash']
            last_hash = row['entry_hash']

        if self.anchor_path.exists():
            anchored = self.anchor_path.read_text(encoding='utf-8').strip()
            if anchored != last_hash:
                return {'ok': False, 'reason': 'audit anchor mismatch', 'sequence': None}
        elif rows:
            return {'ok': False, 'reason': 'audit anchor missing', 'sequence': None}
        return {'ok': True, 'entries': len(rows), 'head_hash': last_hash}
