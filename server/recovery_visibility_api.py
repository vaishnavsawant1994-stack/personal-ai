from __future__ import annotations

from fastapi import APIRouter, HTTPException

from recovery.visibility_projection import ExecutionRecoveryProjection
from security.request_context import current_trusted_request


def recovery_visibility_router(runtime):
    """Read-only visibility; W7 remains execution/verification/recovery authority."""
    router=APIRouter(prefix='/iphone/api/execution-recovery',tags=['execution-recovery'])
    registry=runtime['device_registry']
    tools=runtime['tools']

    def require_owner():
        context=current_trusted_request()
        if context is None:raise HTTPException(401,'Trusted owner session required')
        if not registry.is_active(context.device_id):raise HTTPException(401,'Trusted device is revoked')
        if hasattr(registry,'authorize') and not registry.authorize(context.device_id,'ai:chat'):
            raise HTTPException(403,'This device is not permitted to inspect execution state')
        return context

    @router.get('/{transaction_id}')
    def detail(transaction_id:str):
        context=require_owner()
        try:authority=tools.ensure_recovery_authority()
        except RuntimeError as exc:raise HTTPException(503,'Recovery authority is unavailable') from exc
        item=ExecutionRecoveryProjection(authority).detail(transaction_id,owner_id='owner',device_id=context.device_id,session_id=context.session_id)
        if item is None:raise HTTPException(404,'Execution transaction not found')
        return item

    return router
