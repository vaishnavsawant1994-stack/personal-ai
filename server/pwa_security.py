from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from security.request_context import current_trusted_request


class PasswordReauthBody(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def pwa_security_router(runtime):
    router = APIRouter(prefix='/iphone/api', tags=['iphone-pwa-security'])
    sessions = runtime['pwa_sessions']
    owner_access = runtime['owner_access']

    def context():
        current = current_trusted_request()
        if current is None:
            raise HTTPException(401, {
                'code': 'session_expired',
                'message': 'This browser session is missing, expired, or revoked.',
            })
        return current

    @router.post('/access/reauth/password')
    def reauth_password(body: PasswordReauthBody):
        current = context()
        if not owner_access.password_configured():
            raise HTTPException(409, {
                'code': 'password_not_configured',
                'message': 'Owner password re-authentication is not configured.',
            })
        if not owner_access.verify_password(body.password):
            raise HTTPException(401, {
                'code': 'reauthentication_failed',
                'message': 'Owner verification failed.',
            })
        if not sessions.mark_reauthenticated(current.session_id):
            raise HTTPException(401, {
                'code': 'session_expired',
                'message': 'This browser session is no longer active.',
            })
        return {'ok': True, 'session_id': current.session_id}

    @router.get('/sessions')
    def list_sessions():
        current = context()
        rows = sessions.active_for_device(current.device_id)
        return {
            'current_session_id': current.session_id,
            'sessions': [
                {
                    'id': row.id,
                    'device_id': row.device_id,
                    'created_at': row.created_at,
                    'last_seen_at': row.last_seen_at,
                    'expires_at': row.expires_at,
                    'reauthenticated_at': row.reauthenticated_at,
                    'current': row.id == current.session_id,
                }
                for row in rows
            ],
        }

    @router.post('/sessions/{session_id}/revoke')
    def revoke_session(session_id: str):
        current = context()
        target = sessions.get(session_id)
        if target is None or target.device_id != current.device_id:
            raise HTTPException(404, {
                'code': 'session_not_found',
                'message': 'That browser session was not found for this trusted device.',
            })
        sessions.revoke(session_id)
        executor = runtime.get('executor')
        cancel_session_turns = getattr(executor, 'cancel_session_turns', None)
        cancelled_turns = int(cancel_session_turns(session_id, reason='session_revoked')) if callable(cancel_session_turns) else 0
        automations = runtime.get('automations')
        cancel_session_runs = getattr(automations, 'cancel_session_runs', None)
        cancelled_workflows = int(cancel_session_runs(session_id, reason='session_revoked')) if callable(cancel_session_runs) else 0
        return {'ok': True, 'revoked': session_id, 'current': session_id == current.session_id, 'cancelled_turns': cancelled_turns, 'cancelled_workflows': cancelled_workflows}

    @router.post('/sessions/revoke-others')
    def revoke_other_sessions():
        current = context()
        count = 0
        for row in sessions.active_for_device(current.device_id):
            if row.id != current.session_id and sessions.revoke(row.id):
                count += 1
                executor = runtime.get('executor')
                cancel_session_turns = getattr(executor, 'cancel_session_turns', None)
                if callable(cancel_session_turns):
                    cancel_session_turns(row.id, reason='session_revoked')
                automations = runtime.get('automations')
                cancel_session_runs = getattr(automations, 'cancel_session_runs', None)
                if callable(cancel_session_runs):
                    cancel_session_runs(row.id, reason='session_revoked')
        return {'ok': True, 'revoked': count, 'current_session_id': current.session_id}

    return router
