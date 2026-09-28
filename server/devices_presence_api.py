from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from devices.presence_projection import DevicesPresenceProjection
from security.request_context import current_trusted_request


def devices_presence_router(runtime: dict) -> APIRouter:
    router = APIRouter(prefix='/iphone/api/devices-presence', tags=['devices-presence'])
    registry = runtime['device_registry']
    projection = DevicesPresenceProjection(registry, runtime.get('device_gateway'))

    def require(scope: str):
        ctx = current_trusted_request()
        if ctx is None:
            raise HTTPException(status_code=401, detail='Trusted session required')
        if not registry.is_active(ctx.device_id):
            raise HTTPException(status_code=401, detail='Device is not active')
        if not registry.authorize(ctx.device_id, scope):
            raise HTTPException(status_code=403, detail='Permission denied')
        return ctx

    def require_fresh_reauthentication(ctx) -> None:
        stamp = getattr(ctx, 'reauthenticated_at', None)
        ttl = max(30, min(int(getattr(runtime.get('executor'), 'reauth_ttl_seconds', 300)), 900))
        if stamp is None:
            raise HTTPException(status_code=403, detail='Fresh reauthentication required')
        try:
            age = time.time() - float(stamp)
        except (TypeError, ValueError):
            raise HTTPException(status_code=403, detail='Fresh reauthentication required')
        if age < 0 or age > ttl:
            raise HTTPException(status_code=403, detail='Fresh reauthentication required')

    @router.get('')
    def list_devices():
        require('device:read')
        return {'devices': projection.list()}

    @router.get('/{device_id}')
    def device_detail(device_id: str):
        require('device:read')
        item = projection.detail(device_id)
        if item is None:
            raise HTTPException(status_code=404, detail='Device not found')
        return item

    @router.delete('/{device_id}')
    def revoke_device(device_id: str):
        ctx = require('device:admin')
        require_fresh_reauthentication(ctx)
        if not device_id or len(device_id) > 200:
            raise HTTPException(status_code=404, detail='Device not found')
        item = projection.detail(device_id)
        if item is None:
            raise HTTPException(status_code=404, detail='Device not found')

        # DeviceRegistry remains canonical trust/revocation authority.
        registry.revoke(device_id)

        # Existing durable session authority invalidates all browser sessions for the device.
        sessions = runtime.get('pwa_sessions')
        revoked_sessions = sessions.revoke_device(device_id) if sessions is not None else 0

        # Presence is transport state only. Drop stale live transport after trust revocation.
        gateway = runtime.get('device_gateway')
        if gateway is not None:
            try:
                gateway.disconnect(device_id)
            except Exception:
                pass

        memory = runtime.get('memory')
        if memory is not None and hasattr(memory, 'audit'):
            memory.audit(
                'device.revoked',
                device_id=device_id,
                actor_device_id=ctx.device_id,
                session_id=ctx.session_id,
                revoked_sessions=int(revoked_sessions),
            )
        return {
            'ok': True,
            'device_id': device_id,
            'trust_state': 'revoked',
            'presence_state': 'revoked',
            'revoked_sessions': int(revoked_sessions),
        }

    return router
