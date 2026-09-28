from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from agent.durable_executor import ApprovalDispatchInProgress, ApprovalRecoveryRequired
from agent.executor import ConfirmationRequired, ReauthenticationRequired
from cloud_runtime.security import CloudSessionStore, DEFAULT_SCOPES, OwnerAuthenticator


@dataclass
class RelayResult:
    status: int
    payload: dict


class SlidingWindowLimiter:
    def __init__(self, limit: int = 30, window_seconds: int = 60):
        self.limit = max(1, limit)
        self.window = max(1, window_seconds)
        self._hits = defaultdict(deque)

    def allow(self, key: str) -> bool:
        stamp = time.time()
        queue = self._hits[key]
        while queue and queue[0] <= stamp - self.window:
            queue.popleft()
        if len(queue) >= self.limit:
            return False
        queue.append(stamp)
        return True


class SecureCloudRelay:
    """Policy boundary between an internet-facing client and the privileged Personal AI runtime."""

    DEVICE_SCOPE_MAP = {
        'ai:chat': 'ai:chat',
        'status:read': 'device:read',
        'memory:read': 'memory:read',
        'approval:read': 'ai:chat',
        'approval:write': 'ai:chat',
    }

    def __init__(self, *, executor, memory, second_brain, device_registry, sessions: CloudSessionStore, owner: OwnerAuthenticator, events=None):
        self.executor = executor
        self.memory = memory
        self.second_brain = second_brain
        self.device_registry = device_registry
        self.sessions = sessions
        self.owner = owner
        self.events = events
        self.rate = SlidingWindowLimiter()
        self._state = 'idle'
        if events:
            events.subscribe('state', self._on_state)

    def _on_state(self, event):
        self._state = str(event.get('state', 'unknown'))

    def _device_scope_allowed(self, device_id: str, cloud_scope: str) -> bool:
        mapped_scope = self.DEVICE_SCOPE_MAP.get(str(cloud_scope))
        authorize = getattr(self.device_registry, 'authorize', None) if self.device_registry is not None else None
        return bool(mapped_scope and callable(authorize) and authorize(device_id, mapped_scope))

    def authenticate(self, token: str, scope: str, nonce: str | None = None):
        session = self.sessions.authenticate(token, scope)
        if not session:
            return RelayResult(401, {'error': 'unauthorized'}), None
        if not self.device_registry or not self.device_registry.is_active(session.device_id):
            self.sessions.revoke(session.id)
            return RelayResult(401, {'error': 'device_revoked'}), None
        if not self._device_scope_allowed(session.device_id, scope):
            return RelayResult(403, {'error': 'device_permission_denied'}), None
        if not self.rate.allow(session.id):
            return RelayResult(429, {'error': 'rate_limited'}), None
        if nonce is not None and not self.sessions.accept_nonce(session.id, nonce):
            return RelayResult(409, {'error': 'replay_detected'}), None
        return None, session

    def issue_session(self, device_id: str, device_token: str):
        if not self.device_registry or not self.device_registry.authenticate(device_id, device_token):
            return RelayResult(401, {'error': 'device_auth_failed'})
        allowed_scopes = tuple(
            scope for scope in DEFAULT_SCOPES if self._device_scope_allowed(device_id, scope)
        )
        if not allowed_scopes:
            return RelayResult(403, {'error': 'device_permission_denied'})
        token, session = self.sessions.issue(device_id, scopes=allowed_scopes)
        self.memory.audit('cloud', 'session_issued', {
            'session_id': session.id,
            'device_id': device_id,
            'expires_at': session.expires_at,
        })
        return RelayResult(200, {
            'session_token': token,
            'session_id': session.id,
            'expires_at': session.expires_at,
            'scopes': list(session.scopes),
        })

    def reauthenticate(self, session, owner_secret: str):
        if not self.owner.verify(owner_secret):
            return RelayResult(401, {'error': 'owner_auth_failed'})
        refreshed = self.sessions.mark_reauthenticated(session.id)
        if refreshed is None:
            return RelayResult(401, {'error': 'session_expired'})
        self.memory.audit('cloud', 'session_reauthenticated', {
            'session_id': session.id,
            'device_id': session.device_id,
        })
        return RelayResult(200, {
            'reauthenticated': True,
            'session_id': session.id,
            'reauthenticated_at': refreshed.reauthenticated_at,
        })

    def revoke_session(self, session_id: str, device_id: str):
        ok = self.sessions.revoke(session_id)
        self.memory.audit('cloud', 'session_revoked', {
            'session_id': session_id,
            'device_id': device_id,
            'ok': ok,
        })
        return RelayResult(200, {'revoked': ok})

    def _live_session(self, session):
        if session is None:
            return None
        lookup = getattr(self.sessions, 'session', None)
        # Compatibility session adapters used by non-cloud callers do not expose
        # durable lookup. Real CloudSessionStore does, and is revalidated here.
        current = lookup(session.id) if callable(lookup) else session
        if current is None or current.device_id != getattr(session, 'device_id', None):
            return None
        if not self.device_registry or not self.device_registry.is_active(current.device_id):
            revoke = getattr(self.sessions, 'revoke', None)
            if callable(revoke):
                revoke(current.id)
            return None
        return current

    def command(self, session, text: str, nonce: str):
        session = self._live_session(session)
        if session is None:
            return RelayResult(401, {'error': 'session_expired_or_revoked'})
        if not self._device_scope_allowed(session.device_id, 'ai:chat'):
            return RelayResult(403, {'error': 'device_permission_denied'})
        if self.sessions.emergency_stopped():
            return RelayResult(423, {'error': 'emergency_stop_active'})
        text = (text or '').strip()
        if not text:
            return RelayResult(400, {'error': 'empty_command'})
        if len(text) > 12000:
            return RelayResult(413, {'error': 'command_too_large'})
        try:
            reply = self.executor.chat(
                text,
                device_id=session.device_id,
                session_id=session.id,
                owner_id='owner',
                reauthenticated_at=session.reauthenticated_at,
            )
            self.memory.audit('cloud', 'command', {
                'device_id': session.device_id,
                'session_id': session.id,
                'ok': True,
            })
            return RelayResult(200, {'reply': reply, 'state': self._state})
        except ConfirmationRequired as exc:
            payload = {
                'approval_required': True,
                'approval_id': exc.approval_id,
                'execution_id': exc.execution_id,
                'tool': exc.tool_name,
                'description': exc.description,
                'expires_at': exc.expires_at,
            }
            self.memory.audit('cloud', 'approval_required', {
                'device_id': session.device_id,
                'session_id': session.id,
                'approval_id': exc.approval_id,
                'tool': exc.tool_name,
            })
            return RelayResult(202, payload)
        except ReauthenticationRequired:
            return RelayResult(401, {'error': 'reauthentication_required'})

    def memory_search(self, session, q: str, include_sensitive: bool = False):
        rows = self.memory.search((q or '').strip(), limit=20)
        allowed = []
        for row in rows:
            sensitivity = str(row.get('sensitivity', 'normal')).lower()
            if sensitivity not in {'normal', 'public'} and not (
                include_sensitive and 'memory:sensitive' in session.scopes
            ):
                continue
            allowed.append({
                key: row.get(key)
                for key in (
                    'id', 'type', 'subject', 'content', 'source', 'confidence',
                    'verified', 'sensitivity', 'created_at', 'updated_at',
                )
            })
        self.memory.audit('cloud', 'memory_search', {
            'device_id': session.device_id,
            'query_length': len(q or ''),
            'count': len(allowed),
        })
        return RelayResult(200, {'results': allowed})

    def status(self, session):
        return RelayResult(200, {
            'state': self._state,
            'emergency_stop': self.sessions.emergency_stopped(),
            'device_id': session.device_id,
            'reauthenticated_at': session.reauthenticated_at,
        })

    def approval(self, session, approval_id: str, decision: str):
        session = self._live_session(session)
        if session is None:
            return RelayResult(401, {'error': 'session_expired_or_revoked'})
        if not self._device_scope_allowed(session.device_id, 'approval:write'):
            return RelayResult(403, {'error': 'device_permission_denied'})
        if self.sessions.emergency_stopped():
            return RelayResult(423, {'error': 'emergency_stop_active'})
        try:
            if decision == 'approve':
                reply = self.executor.approve(
                    approval_id,
                    device_id=session.device_id,
                    session_id=session.id,
                    owner_id='owner',
                    reauthenticated_at=session.reauthenticated_at,
                )
            elif decision == 'reject':
                reply = self.executor.reject(
                    approval_id,
                    device_id=session.device_id,
                    session_id=session.id,
                )
            else:
                return RelayResult(400, {'error': 'invalid_decision'})
            self.memory.audit('cloud', 'approval_decision', {
                'device_id': session.device_id,
                'session_id': session.id,
                'approval_id': approval_id,
                'decision': decision,
            })
            return RelayResult(200, {'reply': reply, 'decision': decision})
        except ConfirmationRequired as exc:
            self.memory.audit('cloud', 'approval_continued_to_approval', {
                'device_id': session.device_id,
                'session_id': session.id,
                'prior_approval_id': approval_id,
                'approval_id': exc.approval_id,
                'tool': exc.tool_name,
            })
            return RelayResult(202, {
                'approval_required': True,
                'approval_id': exc.approval_id,
                'execution_id': exc.execution_id,
                'tool': exc.tool_name,
                'description': exc.description,
                'expires_at': exc.expires_at,
                'prior_approval_id': approval_id,
            })
        except ReauthenticationRequired:
            return RelayResult(401, {'error': 'reauthentication_required'})
        except ApprovalDispatchInProgress:
            return RelayResult(409, {'error': 'approval_in_progress'})
        except ApprovalRecoveryRequired:
            return RelayResult(409, {'error': 'approval_recovery_required'})
        except PermissionError:
            return RelayResult(410, {'error': 'approval_unavailable'})

    def set_emergency_stop(self, owner_secret: str, enabled: bool):
        if not self.owner.verify(owner_secret):
            return RelayResult(401, {'error': 'owner_auth_failed'})
        self.sessions.set_emergency_stop(enabled)
        tools = getattr(self.executor, 'tools', None)
        if tools is not None and hasattr(tools, 'set_emergency_stop'):
            tools.set_emergency_stop(enabled)
        if enabled and hasattr(self.executor, 'invalidate_pending_approvals'):
            self.executor.invalidate_pending_approvals()
        if enabled and hasattr(self.executor, 'cancel_active_turns'):
            self.executor.cancel_active_turns(reason='emergency_stop')
        self.memory.audit('cloud', 'emergency_stop', {'enabled': enabled})
        if self.events:
            self.events.emit('emergency.stop', enabled=enabled)
        return RelayResult(200, {'emergency_stop': enabled})