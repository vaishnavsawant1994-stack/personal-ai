from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel, Field


class SnoozeBody(BaseModel):
    until: str = Field(min_length=1, max_length=80)
    timezone: str | None = Field(default=None, max_length=80)


class RescheduleBody(BaseModel):
    due_at: str = Field(min_length=1, max_length=80)
    timezone: str | None = Field(default=None, max_length=80)


def everyday_intelligence_router(runtime):
    """Trusted owner inspection/control for deterministic P4 lifecycle state."""

    router = APIRouter(prefix='/iphone/api/everyday', tags=['everyday-intelligence'])
    registry = runtime['device_registry']
    everyday = runtime['everyday_intelligence']

    def authenticate(device_id: str | None, token: str | None):
        if not device_id or not token or not registry.authenticate(device_id, token):
            raise HTTPException(401, 'This browser is not trusted or its session was revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, 'ai:chat'):
            raise HTTPException(403, 'This device is not permitted to use everyday intelligence')
        return device_id

    def allowed_memory(device_id: str):
        allowed = {'normal'}
        if not hasattr(registry, 'authorize') or registry.authorize(device_id, 'memory:sensitive'):
            allowed.update({'sensitive', 'secret'})
        return allowed

    @router.get('/active')
    def active(
        limit: int = Query(default=100, ge=1, le=500),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        return {'items': everyday.items(status='open', limit=limit)}

    @router.get('/due')
    def due(
        include_surfaced: bool = False,
        limit: int = Query(default=100, ge=1, le=500),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        return {'items': everyday.due_items(include_surfaced=include_surfaced, limit=limit)}

    @router.get('/briefing')
    def briefing(
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        return everyday.briefing(allowed_sensitivities=allowed_memory(device_id))

    @router.get('/{item_id}/history')
    def history(
        item_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        if not everyday.get(item_id):
            raise HTTPException(404, 'Everyday item not found')
        return {'item_id': item_id, 'history': everyday.history(item_id)}

    @router.get('/{item_id}/context')
    def context(
        item_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        if not everyday.get(item_id):
            raise HTTPException(404, 'Everyday item not found')
        return {'item_id': item_id, 'memories': everyday.context_for_item(item_id, allowed_sensitivities=allowed_memory(device_id))}

    @router.post('/{item_id}/complete')
    def complete(
        item_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        if not everyday.complete(item_id):
            raise HTTPException(409, 'Everyday item cannot be completed')
        return everyday.get(item_id)

    @router.post('/{item_id}/snooze')
    def snooze(
        item_id: str,
        body: SnoozeBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        if not everyday.snooze(item_id, body.until, timezone_name=body.timezone):
            raise HTTPException(409, 'Everyday item cannot be snoozed')
        return everyday.get(item_id)

    @router.post('/{item_id}/reschedule')
    def reschedule(
        item_id: str,
        body: RescheduleBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        if not everyday.reschedule(item_id, body.due_at, timezone_name=body.timezone):
            raise HTTPException(409, 'Everyday item cannot be rescheduled')
        return everyday.get(item_id)

    @router.post('/{item_id}/cancel')
    def cancel(
        item_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        if not everyday.cancel(item_id):
            raise HTTPException(409, 'Everyday item cannot be cancelled')
        return everyday.get(item_id)

    return router
