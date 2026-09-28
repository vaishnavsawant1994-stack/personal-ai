from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel, Field

from security.request_context import current_trusted_request


class OperationStepBody(BaseModel):
    requested_tool: str = Field(min_length=1, max_length=160)
    instruction: str = Field(default='', max_length=1000)
    parameters: dict = Field(default_factory=dict)
    sensitivity: str = Field(default='internal', max_length=40)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)


class OperationPlanBody(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    steps: list[OperationStepBody] = Field(min_length=1, max_length=50)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    memory_ids: list[str] = Field(default_factory=list, max_length=100)
    everyday_item_id: str | None = Field(default=None, max_length=200)
    budget_policy: dict = Field(default_factory=dict)


class EverydayOperationBody(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    steps: list[OperationStepBody] = Field(min_length=1, max_length=50)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    budget_policy: dict = Field(default_factory=dict)


class ExecuteBody(BaseModel):
    background: bool = False


class RecoveryLinkBody(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=240)


def personal_operations_router(runtime):
    """Trusted owner inspection/control for P6 governed delegation state."""

    router = APIRouter(prefix='/iphone/api/operations', tags=['personal-operations'])
    registry = runtime['device_registry']
    operations = runtime['personal_operations']

    def authenticate(device_id: str | None, token: str | None):
        if not device_id or not token or not registry.authenticate(device_id, token):
            raise HTTPException(401, 'This browser is not trusted or its session was revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, 'ai:chat'):
            raise HTTPException(403, 'This device is not permitted to use personal operations')
        return device_id

    def allowed_memory(device_id: str):
        allowed = {'normal'}
        if not hasattr(registry, 'authorize') or registry.authorize(device_id, 'memory:sensitive'):
            allowed.update({'sensitive', 'secret'})
        return allowed

    def authority(device_id: str):
        context = current_trusted_request()
        if context is None:
            raise HTTPException(401, 'A trusted browser session is required for operation execution')
        if context.device_id != device_id:
            raise HTTPException(403, 'Authenticated browser session does not match this device')
        return {
            'owner_id': 'owner',
            'device_id': device_id,
            'session_id': context.session_id,
            'reauthenticated_at': context.reauthenticated_at,
        }

    def steps(body_steps):
        return [item.model_dump() for item in body_steps]

    @router.get('')
    def list_operations(
        status: str = Query(default='all', max_length=40),
        limit: int = Query(default=100, ge=1, le=500),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        auth = authority(device_id)
        binding = {
            'owner_id': auth['owner_id'],
            'device_id': auth['device_id'],
            'session_id': auth['session_id'],
        }
        return {
            'operations': operations.operations(status=status, limit=limit, **binding),
            'status': operations.safe_status(**binding),
        }

    @router.post('/plans')
    def create_plan(
        body: OperationPlanBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        try:
            plan = operations.create_plan(
                body.title,
                steps(body.steps),
                owner_id='owner',
                source_refs=body.source_refs,
                memory_ids=body.memory_ids,
                everyday_item_id=body.everyday_item_id,
                budget_policy=body.budget_policy,
                allowed_sensitivities=allowed_memory(device_id),
            )
            return operations.plan_summary(plan['id'])
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (ValueError, RuntimeError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post('/from-everyday/{item_id}')
    def create_from_everyday(
        item_id: str,
        body: EverydayOperationBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        try:
            plan = operations.create_from_everyday(
                item_id,
                body.title,
                steps(body.steps),
                owner_id='owner',
                source_refs=body.source_refs,
                budget_policy=body.budget_policy,
                allowed_sensitivities=allowed_memory(device_id),
            )
            return operations.plan_summary(plan['id'])
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (ValueError, RuntimeError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post('/plans/{plan_id}/execute')
    def execute_plan(
        plan_id: str,
        body: ExecuteBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        auth = authority(device_id)
        try:
            return operations.execute(plan_id, background=body.background, **auth)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get('/{operation_id}')
    def operation_detail(
        operation_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        auth = authority(device_id)
        value = operations.operation(
            operation_id,
            owner_id=auth['owner_id'],
            device_id=auth['device_id'],
            session_id=auth['session_id'],
        )
        if not value:
            raise HTTPException(404, 'Operation not found')
        return value

    @router.post('/{operation_id}/approve')
    def approve(
        operation_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        auth = authority(device_id)
        try:
            return operations.approve(operation_id, **auth)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post('/{operation_id}/reject')
    def reject(
        operation_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        auth = authority(device_id)
        try:
            return operations.reject(
                operation_id,
                owner_id=auth['owner_id'],
                device_id=auth['device_id'],
                session_id=auth['session_id'],
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post('/{operation_id}/cancel')
    def cancel(
        operation_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        auth = authority(device_id)
        try:
            return operations.cancel(
                operation_id,
                owner_id=auth['owner_id'],
                device_id=auth['device_id'],
                session_id=auth['session_id'],
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post('/{operation_id}/recovery/link')
    def link_recovery(
        operation_id: str,
        body: RecoveryLinkBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        auth = authority(device_id)
        try:
            return operations.attach_recovery(
                operation_id, body.transaction_id, owner_id=auth['owner_id'],
                device_id=auth['device_id'], session_id=auth['session_id'],
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post('/{operation_id}/recovery/refresh')
    def refresh_recovery(
        operation_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        auth = authority(device_id)
        try:
            return operations.refresh_recovery(
                operation_id, owner_id=auth['owner_id'],
                device_id=auth['device_id'], session_id=auth['session_id'],
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
