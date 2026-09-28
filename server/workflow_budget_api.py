from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from automation.budget import WorkflowBudgetError
from security.request_context import current_trusted_request


class WorkflowBudgetOverrideBody(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)


def workflow_budget_router(runtime):
    router = APIRouter(prefix='/iphone/api', tags=['workflow-budgets'])
    registry = runtime['device_registry']
    engine = runtime['automations']

    def authenticate(device_id: str | None, token: str | None, scope: str):
        if not device_id or not token or not registry.authenticate(device_id, token):
            raise HTTPException(401, 'This browser is not trusted or its session was revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, scope):
            raise HTTPException(403, f'This device is not permitted to use {scope}')
        return device_id

    @router.get('/workflows/runs/{run_id}/budget')
    def budget_status(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:read')
        try:
            run = engine._run(run_id)
            context = current_trusted_request()
            if run.get('device_id') is not None and run.get('device_id') != device_id:
                raise HTTPException(404, 'Workflow run not found')
            if run.get('session_id') is not None and (context is None or context.device_id != device_id or context.session_id != run.get('session_id')):
                raise HTTPException(404, 'Workflow run not found')
            return engine.budget_status(run_id)
        except HTTPException: raise
        except KeyError as exc: raise HTTPException(404, 'Workflow run not found') from exc

    @router.post('/workflows/runs/{run_id}/budget/override')
    def budget_override(run_id: str, body: WorkflowBudgetOverrideBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:approve')
        context = current_trusted_request()
        if context is None or context.device_id != device_id:
            raise HTTPException(401, 'An authenticated browser session is required')
        if not body.updates or len(body.updates) > 20:
            raise HTTPException(422, 'A bounded workflow budget update is required')
        try:
            result = engine.override_run_budget(run_id, body.updates, owner_id='owner', device_id=device_id, session_id=context.session_id, reauthenticated_at=context.reauthenticated_at)
        except KeyError as exc: raise HTTPException(404, 'Workflow run not found') from exc
        except WorkflowBudgetError as exc: raise HTTPException(409, exc.user_message) from exc
        except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
        except (TypeError, ValueError) as exc: raise HTTPException(422, str(exc)) from exc
        return {'budget': result, 'state': 'Recovery review required'}

    return router
