from __future__ import annotations

from agent.executor import ReauthenticationRequired
from core.personal_ai_runtime import TurnReplayBlocked
from models.router import ModelError
from security.request_context import current_trusted_request
from server.logical_request_middleware import current_logical_request_id


class OwnerReauthenticationRequired(ModelError):
    code = 'reauthentication_required'
    status_code = 401
    user_message = 'This critical action requires a recent owner verification. Verify your owner password or passkey and try again.'


class CanonicalTurnInProgress(ModelError):
    code = 'turn_in_progress'
    status_code = 409
    user_message = 'This request is already in progress or waiting for its governed continuation.'


class SessionBoundExecutor:
    """Bind an authenticated browser session to the canonical Personal AI runtime."""

    def __init__(self, executor, *, continuity=None, surface: str = 'pwa'):
        self._executor = executor
        self._surface = str(surface or 'pwa')
        self._continuity = continuity

    def __getattr__(self, name):
        return getattr(self._executor, name)

    @staticmethod
    def _context():
        context = current_trusted_request()
        if context is None:
            raise PermissionError('trusted browser session is required')
        return context

    @staticmethod
    def _check_device(explicit_device_id, context):
        if explicit_device_id is not None and explicit_device_id != context.device_id:
            raise PermissionError('trusted browser session device mismatch')

    @staticmethod
    def _translate_reauth(callback):
        try:
            return callback()
        except ReauthenticationRequired as exc:
            raise OwnerReauthenticationRequired(exc.reason) from exc

    @staticmethod
    def _owner_only(kwargs):
        owner = str(kwargs.get('owner_id') or 'owner')
        if owner != 'owner':
            raise PermissionError('authenticated Personal AI surfaces are owner-only')

    def chat(self, text, **kwargs):
        context = self._context()
        self._check_device(kwargs.get('device_id'), context)
        self._owner_only(kwargs)
        call_kwargs = dict(kwargs)
        call_kwargs['owner_id'] = 'owner'
        call_kwargs['device_id'] = context.device_id
        call_kwargs['session_id'] = context.session_id
        call_kwargs['reauthenticated_at'] = context.reauthenticated_at
        call_kwargs.setdefault('surface', self._surface)
        logical_request_id = current_logical_request_id()
        if logical_request_id:
            explicit = call_kwargs.get('request_id')
            if explicit is not None and str(explicit) != logical_request_id:
                raise PermissionError('logical request identity mismatch')
            call_kwargs['request_id'] = logical_request_id
        try:
            return self._translate_reauth(lambda: self._executor.chat(text, **call_kwargs))
        except TurnReplayBlocked as exc:
            raise CanonicalTurnInProgress(str(exc)) from exc

    def cancel_turn(self, request_id: str | None = None):
        context = self._context()
        logical_request_id = current_logical_request_id()
        request_id = str(request_id or logical_request_id or '').strip()
        if not request_id:
            return None
        cancel = getattr(self._executor, 'cancel_turn', None)
        if not callable(cancel):
            return None
        return cancel(
            request_id,
            owner_id='owner',
            device_id=context.device_id,
            session_id=context.session_id,
        )

    def approve(self, approval_id: str, **kwargs):
        context = self._context()
        self._check_device(kwargs.get('device_id'), context)
        self._owner_only(kwargs)
        call_kwargs = {
            'owner_id': 'owner',
            'device_id': context.device_id,
            'session_id': context.session_id,
            'reauthenticated_at': context.reauthenticated_at,
        }
        return self._translate_reauth(lambda: self._executor.approve(approval_id, **call_kwargs))

    def reject(self, approval_id: str, **kwargs):
        context = self._context()
        self._check_device(kwargs.get('device_id'), context)
        self._owner_only(kwargs)
        return self._executor.reject(
            approval_id,
            device_id=context.device_id,
            session_id=context.session_id,
        )
