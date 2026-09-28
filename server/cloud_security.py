from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse


def cloud_security_router(runtime):
    router = APIRouter(prefix='/cloud', tags=['cloud-security'])

    @router.post('/reauth')
    def reauthenticate(
        authorization: str | None = Header(default=None),
        x_personal_ai_owner_key: str | None = Header(default=None),
    ):
        relay = runtime.get('cloud_relay')
        if relay is None:
            raise HTTPException(404, 'Cloud runtime disabled')
        token = (authorization or '').removeprefix('Bearer ').strip()
        error, session = relay.authenticate(token, 'status:read')
        if error:
            return JSONResponse(status_code=error.status, content=error.payload)
        result = relay.reauthenticate(session, x_personal_ai_owner_key or '')
        return JSONResponse(status_code=result.status, content=result.payload)

    return router
