from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path

from apps_tools.projection import AppsToolsProjection
from security.request_context import current_trusted_request


def apps_tools_router(runtime):
    """Authorized metadata transport; never executes tools or owns connection truth."""
    router = APIRouter(prefix='/iphone/api/apps-tools', tags=['apps-tools'])
    devices = runtime['device_registry']
    projection = AppsToolsProjection(runtime['tools'], runtime.get('integrations'), runtime.get('memory'))

    def require_owner(scope='device:read'):
        context = current_trusted_request()
        if context is None:
            raise HTTPException(401, 'Trusted owner session required')
        if not devices.is_active(context.device_id):
            raise HTTPException(401, 'Trusted device is revoked')
        if not hasattr(devices, 'authorize') or not devices.authorize(context.device_id, scope):
            raise HTTPException(403, f'This device is not permitted to use {scope}')
        return context

    @router.get('/tools')
    def list_tools():
        require_owner()
        return {'tools': projection.tools_list()}

    @router.get('/tools/{tool_id}')
    def tool_detail(tool_id: str = Path(..., min_length=1, max_length=200)):
        require_owner()
        item = projection.tool_detail(tool_id)
        if item is None:
            raise HTTPException(404, 'Tool not found')
        return {'tool': item}

    @router.get('/apps')
    def list_apps():
        require_owner()
        return {'apps': projection.apps_list()}

    @router.get('/apps/{app_id}')
    def app_detail(app_id: str = Path(..., min_length=1, max_length=200)):
        require_owner()
        item = projection.app_detail(app_id)
        if item is None:
            raise HTTPException(404, 'App not found')
        return {'app': item}

    return router
