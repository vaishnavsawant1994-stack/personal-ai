from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from automation.projection import AutomationWorkflowProjection
from security.request_context import current_trusted_request


def automation_visibility_router(runtime):
    """Read-only Stage-6 transport over the canonical AutomationEngine."""
    router = APIRouter(prefix='/iphone/api/automation-visibility', tags=['automation-visibility'])
    registry = runtime['device_registry']
    projection = AutomationWorkflowProjection(runtime['automations'])

    def require_owner(scope='workflow:read'):
        context = current_trusted_request()
        if context is None:
            raise HTTPException(401, 'Trusted owner session required')
        if not registry.is_active(context.device_id):
            raise HTTPException(401, 'Trusted device is revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(context.device_id, scope):
            raise HTTPException(403, f'This device is not permitted to use {scope}')
        return context

    @router.get('/automations')
    def automations(limit: int = Query(default=50, ge=1, le=100)):
        require_owner()
        return {'automations': projection.automations(limit=limit)}

    @router.get('/workflows')
    def workflows(limit: int = Query(default=50, ge=1, le=100)):
        require_owner()
        return {'workflows': projection.workflows(limit=limit)}

    @router.get('/runs')
    def runs(workflow_id: str | None = None, limit: int = Query(default=50, ge=1, le=100)):
        context = require_owner()
        return {'runs': projection.runs(
            workflow_id=workflow_id,
            owner_id='owner',
            device_id=context.device_id,
            session_id=context.session_id,
            limit=limit,
        )}

    return router
