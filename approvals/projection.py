from __future__ import annotations

import time
from typing import Any

from security.projection_redaction import sanitize_sensitive_text


class ApprovalsProjection:
    """Read-only owner projection over the Stage-2 durable ApprovalManager.

    It never creates, decides, dispatches or recovers work. ApprovalManager is
    the sole authority; this layer only produces bounded owner-safe metadata.
    """

    MAX_ITEMS = 100
    _SECRET_FRAGMENTS = (
        'password', 'secret', 'credential', 'api_key', 'apikey', 'access_token',
        'refresh_token', 'authorization', 'cookie', 'private_key', 'client_secret', 'token', 'headers', 'provider_config', 'raw_prompt', 'system_prompt',
    )

    def __init__(self, manager): self.manager = manager

    @classmethod
    def _safe(cls, value: Any, *, depth: int = 0):
        if depth > 6: return '[bounded]'
        if isinstance(value, dict):
            out = {}
            for key, item in list(value.items())[:60]:
                normalized = str(key).lower().replace('-', '_').replace(' ', '_')
                out[str(key)] = '[redacted]' if any(x in normalized for x in cls._SECRET_FRAGMENTS) else cls._safe(item, depth=depth + 1)
            return out
        if isinstance(value, (list, tuple)): return [cls._safe(x, depth=depth + 1) for x in list(value)[:60]]
        if isinstance(value, str): return sanitize_sensitive_text(value)[:1000]
        if value is None or isinstance(value, (bool, int, float)): return value
        return str(value)[:1000]

    @staticmethod
    def _status(record, ticket, now):
        status = str(record.get('status') or 'pending')
        return 'expired' if status == 'pending' and now >= float(ticket.expires_at) else status

    def project_record(self, record, *, now=None):
        ticket = record['ticket']; now = time.time() if now is None else float(now)
        return {
            'approval_id': ticket.id,
            'execution_id': ticket.execution_id,
            'tool_id': ticket.tool_name,
            'status': self._status(record, ticket, now),
            'created_at': ticket.created_at,
            'expires_at': ticket.expires_at,
            'destination': '[redacted]' if str(ticket.destination or '').lower().startswith(('javascript:', 'data:', 'vbscript:')) else sanitize_sensitive_text(str(ticket.destination or ''))[:1000],
            'data_classification': str(ticket.data_classification or 'internal')[:40],
            'device_bound': ticket.device_id is not None,
            'session_bound': ticket.session_id is not None,
            'dispatch_started_at': record.get('dispatch_started_at'),
            'completed_at': record.get('completed_at'),
            'failure_code': str(record.get('failure_code') or '')[:160] or None,
            'outcome': self._safe(record.get('outcome')) if record.get('outcome') is not None else None,
        }

    def detail(self, approval_id, *, owner_id='owner', device_id=None, session_id=None):
        record = self.manager.record(str(approval_id))
        if record is None: return None
        ticket = record['ticket']
        if ticket.owner_id != owner_id: return None
        if ticket.device_id not in (None, device_id): return None
        if ticket.session_id not in (None, session_id): return None
        return self.project_record(record)

    def pending(self, *, owner_id='owner', device_id=None, session_id=None, limit=50):
        limit = max(1, min(int(limit), self.MAX_ITEMS))
        rows = self.manager.list_pending(owner_id=owner_id, device_id=device_id, session_id=session_id)
        # list_pending is already a safe Stage-2 projection. Normalize names for
        # the owner surface without reading continuation payloads or parameters.
        return [{
            'approval_id': row['approval_id'], 'execution_id': row['execution_id'],
            'tool_id': row['action'], 'status': row['status'],
            'created_at': row['created_at'], 'expires_at': row['expires_at'],
            'destination': str(row.get('destination') or '')[:200],
            'data_classification': str(row.get('data_classification') or 'internal')[:40],
            'device_bound': row.get('device_id') is not None,
            'session_bound': row.get('session_id') is not None,
        } for row in rows[:limit]]
