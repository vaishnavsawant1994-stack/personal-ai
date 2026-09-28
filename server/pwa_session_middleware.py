from __future__ import annotations

from http.cookies import SimpleCookie

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from security.request_context import (
    TrustedRequestContext,
    reset_trusted_request,
    set_trusted_request,
)


PUBLIC_PATHS = {
    '/iphone',
    '/iphone/',
    '/iphone/manifest.webmanifest',
    '/iphone/sw.js',
    '/iphone/api/access/options',
    '/iphone/api/access/google/login',
    '/iphone/api/access/password/login',
    '/iphone/api/access/recovery/login',
    '/iphone/api/access/passkey/login/options',
    '/iphone/api/access/passkey/login/complete',
    '/iphone/api/enroll',
}

LOGIN_PATHS = {
    '/iphone/api/access/google/login',
    '/iphone/api/access/password/login',
    '/iphone/api/access/recovery/login',
    '/iphone/api/access/passkey/login/complete',
    '/iphone/api/enroll',
}


def _is_public(path: str) -> bool:
    return path in PUBLIC_PATHS


def _cookie_from_response(response, name: str) -> str | None:
    for raw_name, raw_value in response.raw_headers:
        if raw_name.lower() != b'set-cookie':
            continue
        jar = SimpleCookie()
        try:
            jar.load(raw_value.decode('latin1'))
        except Exception:
            continue
        morsel = jar.get(name)
        if morsel and morsel.value:
            return morsel.value
    return None


class PwaSessionMiddleware(BaseHTTPMiddleware):
    """Require a revocable server-side session in addition to the device bearer."""

    def __init__(self, app, *, sessions, device_registry, cookie_max_age: int):
        super().__init__(app)
        self.sessions = sessions
        self.device_registry = device_registry
        self.cookie_max_age = max(300, int(cookie_max_age))

    def _set_session_cookie(self, response, token: str):
        response.set_cookie(
            'pa_session',
            token,
            httponly=True,
            secure=True,
            samesite='strict',
            path='/iphone',
            max_age=self.cookie_max_age,
        )

    @staticmethod
    def _clear_session_cookie(response):
        response.delete_cookie('pa_session', path='/iphone')

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith('/iphone'):
            return await call_next(request)

        context_token = None
        session = None
        session_token = request.cookies.get('pa_session')
        device_id = request.cookies.get('pa_device')

        if not _is_public(path):
            session = self.sessions.authenticate(session_token, device_id)
            if session is None:
                response = JSONResponse(
                    status_code=401,
                    content={
                        'detail': {
                            'code': 'session_expired',
                            'message': 'This browser session is missing, expired, or revoked. Sign in again.',
                        }
                    },
                )
                self._clear_session_cookie(response)
                return response
            if not self.device_registry.is_active(session.device_id):
                self.sessions.revoke(session.id)
                response = JSONResponse(
                    status_code=401,
                    content={
                        'detail': {
                            'code': 'device_revoked',
                            'message': 'This trusted device has been revoked.',
                        }
                    },
                )
                self._clear_session_cookie(response)
                return response
            context_token = set_trusted_request(
                TrustedRequestContext(
                    device_id=session.device_id,
                    session_id=session.id,
                    reauthenticated_at=session.reauthenticated_at,
                )
            )

        try:
            response = await call_next(request)
        finally:
            if context_token is not None:
                reset_trusted_request(context_token)

        if path in LOGIN_PATHS and response.status_code < 400:
            new_device_id = _cookie_from_response(response, 'pa_device')
            if new_device_id and self.device_registry.is_active(new_device_id):
                new_token, _ = self.sessions.issue(new_device_id, reauthenticated=True)
                self._set_session_cookie(response, new_token)

        if path == '/iphone/api/logout':
            if session is not None:
                self.sessions.revoke(session.id)
            elif session_token:
                self.sessions.revoke_token(session_token)
            self._clear_session_cookie(response)

        return response
