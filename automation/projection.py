from __future__ import annotations

import json
from typing import Any

from security.projection_redaction import sanitize_sensitive_text


class AutomationWorkflowProjection:
    """Owner-safe read projection over the existing AutomationEngine.

    The AutomationEngine remains the sole scheduler/workflow authority.  This
    projection never schedules, runs, resumes, approves, or mutates work.
    """

    MAX_ITEMS = 100
    MAX_TEXT = 1000
    _SECRET_FRAGMENTS = (
        'password', 'secret', 'credential', 'api_key', 'apikey', 'access_token',
        'refresh_token', 'authorization', 'cookie', 'private_key', 'client_secret',
    )

    def __init__(self, engine):
        self.engine = engine

    @classmethod
    def _safe(cls, value: Any, *, depth: int = 0):
        if depth > 6:
            return '[bounded]'
        if isinstance(value, dict):
            out = {}
            for key, item in list(value.items())[:60]:
                normalized = str(key).lower().replace('-', '_').replace(' ', '_')
                if any(fragment in normalized for fragment in cls._SECRET_FRAGMENTS):
                    out[str(key)] = '[redacted]'
                else:
                    out[str(key)] = cls._safe(item, depth=depth + 1)
            return out
        if isinstance(value, (list, tuple)):
            return [cls._safe(item, depth=depth + 1) for item in list(value)[:60]]
        if isinstance(value, str):
            return sanitize_sensitive_text(value)[:cls.MAX_TEXT]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:cls.MAX_TEXT]

    @classmethod
    def _json(cls, raw, default):
        try:
            return cls._safe(json.loads(raw)) if raw else default
        except (TypeError, ValueError, json.JSONDecodeError):
            return default

    def automations(self, *, limit=50):
        limit = max(1, min(int(limit), self.MAX_ITEMS))
        rows = self.engine.list()[:self.MAX_ITEMS]
        out = []
        for row in rows:
            result = self._json(row.get('last_result_json'), None)
            out.append({
                'automation_id': str(row.get('id')),
                'title': str(row.get('title') or '')[:200],
                'enabled': bool(row.get('enabled')),
                'next_run_at': row.get('next_run_at'),
                'last_run_at': row.get('last_run_at'),
                'interval_seconds': row.get('interval_seconds'),
                'condition': self._json(row.get('condition_json'), {}),
                'last_result': result,
                'approval_id': result.get('approval_id') if isinstance(result, dict) else None,
            })
        return out[:limit]

    def workflows(self, *, limit=50):
        limit = max(1, min(int(limit), self.MAX_ITEMS))
        out = []
        for row in self.engine.workflows()[:self.MAX_ITEMS]:
            trigger = self._safe(row.get('trigger') or {})
            out.append({
                'workflow_id': str(row.get('id')),
                'title': str(row.get('title') or '')[:200],
                'enabled': bool(row.get('enabled')),
                'paused': bool(row.get('paused')),
                'trigger': trigger,
                'next_run_at': row.get('next_run_at'),
                'last_run_at': row.get('last_run_at'),
                'interval_seconds': row.get('interval_seconds'),
                'step_count': min(len(row.get('steps') or []), 50),
                'policy': self._safe(row.get('policy') or {}),
            })
        return out[:limit]

    def runs(self, *, workflow_id=None, owner_id='owner', device_id=None, session_id=None, limit=50):
        limit = max(1, min(int(limit), self.MAX_ITEMS))
        rows = self.engine.runs(workflow_id=workflow_id, limit=self.MAX_ITEMS)
        out = []
        for row in rows:
            if row.get('owner_id') not in (None, owner_id):
                continue
            if row.get('device_id') not in (None, device_id):
                continue
            # Engine deliberately strips session_id from runs(); use its narrow
            # canonical binding reader instead of reaching into a private run record.
            try:
                canonical = self.engine.run_binding(row['id'])
            except Exception:
                continue
            if not canonical or canonical.get('session_id') not in (None, session_id):
                continue
            out.append({
                'run_id': str(row.get('id')),
                'workflow_id': str(row.get('workflow_id')),
                'status': str(row.get('status') or 'unknown')[:80],
                'current_step': int(row.get('current_step') or 0),
                'pending_approval_id': row.get('pending_approval_id'),
                'started_at': row.get('started_at'),
                'updated_at': row.get('updated_at'),
                'completed_at': row.get('completed_at'),
                # Engine errors may originate in providers and can echo URLs, headers or credentials.\n                # Keep the owner semantic without forwarding arbitrary provider text.\n                'error': 'Workflow run reported an error' if row.get('error') else None,
                'result': self._json(row.get('result_json'), None),
                'budget': self._safe(row.get('budget')),
            })
        return out[:limit]
