from __future__ import annotations

import base64
import json
import re
from copy import deepcopy

from security.projection_redaction import sanitize_sensitive_text


_SECRET_KEYS = re.compile(
    r'(api[_-]?key|authorization|cookie|session[_-]?(token|secret)|access[_-]?token|refresh[_-]?token|'
    r'approval[_-]?token|recovery[_-]?(credential|secret|token)|credential|password|private[_-]?key|'
    r'client[_-]?secret|(^|[_-])secret($|[_-])|secret[_-]?env)',
    re.IGNORECASE,
)
_SENSITIVE_CONTEXT_KEYS = re.compile(
    r'(raw_(memory|knowledge|audio|camera|location|prompt|screen)|system_prompt|provider_config|headers)',
    re.IGNORECASE,
)


class ActivitiesProjection:
    """User-safe projection over the canonical audit ledger.

    Audit remains the evidence authority. This class never mutates or replaces
    audit data; it returns a recursively sanitized, bounded owner-facing view.
    Pagination is a bounded snapshot over the canonical newest 1,000 Audit rows:
    a cursor binds the query, the first row visible on page one, and the last
    emitted row. Newer Audit writes are excluded on later pages. If the upstream
    1,000-row window can no longer reconstruct that snapshot, pagination fails
    closed as stale instead of silently duplicating or skipping records.
    """

    CATEGORY_LABELS = {
        'agent': 'Personal AI', 'approval': 'Approval', 'tool': 'Tool',
        'memory': 'Memory', 'knowledge': 'Knowledge', 'automation': 'Automation',
        'workflow': 'Workflow', 'model': 'Model', 'continuity': 'Continuity',
        'owner-product': 'Owner action', 'recovery': 'Recovery',
        'verification': 'Verification',
    }
    MAX_PAGE = 200
    MAX_SCAN = 1000

    def __init__(self, audit_store):
        self.audit_store = audit_store

    @classmethod
    def _sanitize(cls, value, *, depth=0):
        if depth > 8:
            return '[bounded]'
        if isinstance(value, dict):
            clean = {}
            for key, item in list(value.items())[:100]:
                name = str(key)[:200]
                if _SECRET_KEYS.search(name) or _SENSITIVE_CONTEXT_KEYS.search(name):
                    clean[name] = '[redacted]'
                else:
                    clean[name] = cls._sanitize(item, depth=depth + 1)
            return clean
        if isinstance(value, (list, tuple)):
            return [cls._sanitize(item, depth=depth + 1) for item in list(value)[:100]]
        if isinstance(value, str):
            return sanitize_sensitive_text(value)[:1000]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:1000]

    @classmethod
    def project_entry(cls, entry: dict) -> dict:
        item = deepcopy(dict(entry))
        category = str(item.get('category') or 'system')[:100]
        action = str(item.get('action') or 'event')[:200]
        payload = cls._sanitize(item.get('payload') or {})
        audit_id = str(item.get('id') or '')[:200]
        return {
            'id': audit_id,
            'activity_id': audit_id,
            'kind': category,
            'label': cls.CATEGORY_LABELS.get(category, category.replace('_', ' ').title()),
            'action': action,
            'status': cls._status(category, action, payload),
            'created_at': item.get('created_at'),
            'details': payload,
        }

    @staticmethod
    def _status(category: str, action: str, payload: dict) -> str:
        text = f'{category}.{action}'.lower()
        if payload.get('ok') is False or any(word in text for word in ('failed', 'error')):
            return 'error'
        if payload.get('verified') is False or any(word in text for word in ('warning', 'unverified', 'recovery')):
            return 'warning'
        if any(word in text for word in ('required', 'pending', 'waiting')):
            return 'needs_approval' if 'approval' in text else 'pending'
        if any(word in text for word in ('approved', 'completed', 'success', 'execute', 'committed')):
            return 'completed'
        if any(word in text for word in ('started', 'running')):
            return 'running'
        return 'recorded'

    @staticmethod
    def _query_binding(category: str | None, status: str | None) -> dict:
        return {
            'category': str(category) if category is not None else None,
            'status': str(status) if status is not None else None,
        }

    @staticmethod
    def _encode_cursor(*, snapshot_id: str, after_id: str, query: dict) -> str:
        raw = json.dumps(
            {'v': 2, 'snapshot': str(snapshot_id), 'after': str(after_id), 'query': query},
            separators=(',', ':'), sort_keys=True,
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')

    @staticmethod
    def _decode_cursor(cursor: str | None) -> tuple[str, str, dict] | None:
        if not cursor:
            return None
        if len(cursor) > 768:
            raise ValueError('invalid activity cursor')
        try:
            padded = cursor + '=' * (-len(cursor) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
            if data.get('v') != 2 or set(data) != {'v', 'snapshot', 'after', 'query'}:
                raise ValueError
            snapshot = str(data.get('snapshot') or '')
            after = str(data.get('after') or '')
            query = data.get('query')
            if not isinstance(query, dict) or set(query) != {'category', 'status'}:
                raise ValueError
            if any(value is not None and not isinstance(value, str) for value in query.values()):
                raise ValueError
            if not snapshot or not after or len(snapshot) > 200 or len(after) > 200:
                raise ValueError
            if any(value is not None and len(value) > 200 for value in query.values()):
                raise ValueError
            return snapshot, after, query
        except Exception as exc:
            raise ValueError('invalid activity cursor') from exc

    def _rows(self, *, category: str | None = None) -> list[dict]:
        rows = list(self.audit_store.audit_entries(category=category, limit=self.MAX_SCAN))
        rows.sort(
            key=lambda row: (str(row.get('created_at') or ''), str(row.get('id') or '')),
            reverse=True,
        )
        return rows

    def page(
        self, *, limit: int = 50, category: str | None = None,
        status: str | None = None, cursor: str | None = None,
    ) -> dict:
        bounded = max(1, min(int(limit), self.MAX_PAGE))
        binding = self._query_binding(category, status)
        decoded = self._decode_cursor(cursor)
        if decoded and decoded[2] != binding:
            raise ValueError('activity cursor does not match query')
        projected = [self.project_entry(row) for row in self._rows(category=category)]
        if status:
            projected = [row for row in projected if row['status'] == str(status)]
        if not projected:
            if decoded:
                raise ValueError('stale activity cursor')
            return {'activities': [], 'next_cursor': None, 'has_more': False}

        if decoded:
            snapshot_id, after_id, _ = decoded
            snapshot_positions = [i for i, row in enumerate(projected) if row['id'] == snapshot_id]
            if not snapshot_positions:
                raise ValueError('stale activity cursor')
            projected = projected[snapshot_positions[0]:]
            after_positions = [i for i, row in enumerate(projected) if row['id'] == after_id]
            if not after_positions:
                raise ValueError('stale or invalid activity cursor')
            projected = projected[after_positions[0] + 1:]
        else:
            snapshot_id = projected[0]['id']

        items = projected[:bounded]
        has_more = len(projected) > bounded
        return {
            'activities': items,
            'next_cursor': self._encode_cursor(
                snapshot_id=snapshot_id, after_id=items[-1]['id'], query=binding,
            ) if has_more and items else None,
            'has_more': has_more,
        }

    def list(self, *, limit: int = 100, category: str | None = None) -> list[dict]:
        return self.page(limit=limit, category=category)['activities']

    def detail(self, activity_id: str) -> dict | None:
        wanted = str(activity_id or '').strip()
        if not wanted or len(wanted) > 200:
            return None
        rows = self._rows()
        match = next((row for row in rows if str(row.get('id') or '') == wanted), None)
        if match is None:
            return None
        projected = self.project_entry(match)
        payload = projected['details'] if isinstance(projected['details'], dict) else {}
        correlation_keys = (
            'request_id', 'turn_id', 'conversation_id', 'plan_id', 'workflow_id',
            'execution_id', 'operation_id', 'approval_id', 'tool_id', 'parent_activity_id',
        )
        correlations = {key: str(payload[key]) for key in correlation_keys if payload.get(key) is not None}
        # Correlate by the strongest canonical identity available. Using OR across
        # every identifier can merge unrelated work that merely shares a broad
        # conversation/request identifier while stronger execution identities
        # conflict.
        correlation_priority = (
            'operation_id', 'execution_id', 'approval_id', 'workflow_id', 'plan_id',
            'turn_id', 'request_id', 'parent_activity_id', 'conversation_id', 'tool_id',
        )
        primary_key = next((key for key in correlation_priority if key in correlations), None)
        timeline = []
        for row in rows:
            event = self.project_entry(row)
            details = event['details'] if isinstance(event['details'], dict) else {}
            include = event['id'] == wanted
            if not include and primary_key is not None:
                include = str(details.get(primary_key)) == correlations[primary_key]
                # A candidate sharing the primary identity must not contradict
                # another stronger canonical identity present on both records.
                if include:
                    primary_index = correlation_priority.index(primary_key)
                    for stronger_key in correlation_priority[:primary_index]:
                        expected = correlations.get(stronger_key)
                        actual = details.get(stronger_key)
                        if expected is not None and actual is not None and str(actual) != expected:
                            include = False
                            break
            if include:
                timeline.append(event)
        timeline.sort(key=lambda row: (str(row.get('created_at') or ''), str(row.get('id') or '')))
        return {**projected, 'correlations': correlations, 'timeline': timeline[:self.MAX_PAGE]}
