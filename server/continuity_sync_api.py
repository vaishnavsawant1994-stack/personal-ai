from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from security.request_context import current_trusted_request


class SyncEventBody(BaseModel):
    client_event_id: str = Field(min_length=1, max_length=160)
    client_sequence: int = Field(ge=1)
    kind: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)


class ReconcileBody(BaseModel):
    security_epoch: int = Field(ge=0)
    thread_id: str | None = Field(default=None, max_length=160)
    after_sequence: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1, le=500)
    events: list[SyncEventBody] = Field(default_factory=list, max_length=100)


class HandoffBody(BaseModel):
    to_device: str = Field(min_length=1, max_length=160)
    thread_id: str | None = Field(default=None, max_length=160)


def continuity_sync_router(runtime):
    """P8 trusted cross-device synchronization API over canonical continuity."""

    router = APIRouter(prefix='/iphone/api/continuity', tags=['cross-device-continuity'])
    sync = runtime['continuity_sync']

    def authority():
        context = current_trusted_request()
        if context is None:
            raise HTTPException(401, {
                'code': 'session_expired',
                'message': 'A live trusted browser session is required for continuity.',
            })
        return {'device_id': context.device_id, 'session_id': context.session_id}

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get('/status')
    def status():
        return call(sync.status, **authority())

    @router.post('/reconcile')
    def reconcile(body: ReconcileBody):
        return call(
            sync.reconcile,
            **authority(),
            security_epoch=body.security_epoch,
            thread_id=body.thread_id,
            after_sequence=body.after_sequence,
            limit=body.limit,
            events=[item.model_dump() for item in body.events],
        )

    @router.post('/handoff')
    def handoff(body: HandoffBody):
        return call(sync.handoff, **authority(), to_device=body.to_device, thread_id=body.thread_id)

    @router.get('/operations/{operation_id}')
    def operation_status(operation_id: str):
        return call(sync.operation_status, operation_id, **authority())

    @router.get('/world/{observation_id}')
    def observation_status(observation_id: str):
        return call(sync.observation_status, observation_id, **authority())

    return router
