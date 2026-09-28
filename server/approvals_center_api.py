from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from approvals.projection import ApprovalsProjection
from security.request_context import current_trusted_request


def approvals_center_router(runtime):
    """Read transport for Approvals Center; Stage-2 endpoints own decisions."""
    router = APIRouter(prefix='/iphone/api/approvals-center', tags=['approvals-center'])
    registry = runtime['device_registry']
    manager = runtime['agent_executor'].approvals
    projection = ApprovalsProjection(manager)

    def require_owner():
        context = current_trusted_request()
        if context is None: raise HTTPException(401, 'Trusted owner session required')
        if not registry.is_active(context.device_id): raise HTTPException(401, 'Trusted device is revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(context.device_id, 'ai:chat'):
            raise HTTPException(403, 'This device is not permitted to inspect governed approvals')
        return context

    @router.get('')
    def approval_list(limit: int = Query(default=50, ge=1, le=100)):
        context = require_owner()
        return {'approvals': projection.pending(owner_id='owner', device_id=context.device_id, session_id=context.session_id, limit=limit)}

    @router.get('/{approval_id}')
    def approval_detail(approval_id: str):
        context = require_owner()
        item = projection.detail(approval_id, owner_id='owner', device_id=context.device_id, session_id=context.session_id)
        if item is None: raise HTTPException(404, {'code':'approval_not_found','message':'This approval is missing or unavailable.'})
        return item

    return router
