from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from integrations.registry import IntegrationRegistry
from memory.store import MemoryStore
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.activities_api import activities_router
from server.apps_tools_api import apps_tools_router
from tools.registry import ToolRegistry


class ContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, device_id='d', session_id='s'):
        super().__init__(app); self.device_id=device_id; self.session_id=session_id
    async def dispatch(self, request, call_next):
        token=set_trusted_request(TrustedRequestContext(self.device_id,self.session_id))
        try: return await call_next(request)
        finally: reset_trusted_request(token)


class Devices:
    def __init__(self, *, active=True, scopes=()): self.active=active; self.scopes=set(scopes)
    def is_active(self, device_id): return self.active and device_id == 'd'
    def authorize(self, device_id, scope): return device_id == 'd' and scope in self.scopes


def activities_app(tmp_path, devices, with_context=True):
    memory=MemoryStore(tmp_path/'activities.sqlite3'); memory.audit('tool','completed',{'tool_id':'safe'})
    app=FastAPI()
    if with_context: app.add_middleware(ContextMiddleware)
    app.include_router(activities_router({'device_registry':devices,'memory':memory}))
    return TestClient(app), memory


def test_activities_requires_trusted_context(tmp_path):
    client,_=activities_app(tmp_path,Devices(active=True,scopes={'activities:read'}),with_context=False)
    assert client.get('/iphone/api/activities').status_code == 401


def test_activities_requires_explicit_read_scope(tmp_path):
    client,_=activities_app(tmp_path,Devices(active=True,scopes={'ai:chat'}))
    assert client.get('/iphone/api/activities').status_code == 403
    assert client.get('/iphone/api/activities/missing').status_code == 403


def test_activities_revoked_or_inactive_device_denied(tmp_path):
    client,_=activities_app(tmp_path,Devices(active=False,scopes={'activities:read'}))
    assert client.get('/iphone/api/activities').status_code == 401
    assert client.get('/iphone/api/activities/missing').status_code == 401


def test_activity_detail_not_found_is_safe_and_list_filters_authorized(tmp_path):
    client,_=activities_app(tmp_path,Devices(active=True,scopes={'activities:read'}))
    assert client.get('/iphone/api/activities/not-real').status_code == 404
    assert client.get('/iphone/api/activities?category=tool&status=completed').status_code == 200


def test_activity_cursor_cannot_bypass_authorization(tmp_path):
    allowed,memory=activities_app(tmp_path,Devices(active=True,scopes={'activities:read'}))
    for i in range(4): memory.audit('tool','completed',{'tool_id':str(i)})
    cursor=allowed.get('/iphone/api/activities?limit=2').json()['next_cursor']
    denied,_=activities_app(tmp_path/'denied',Devices(active=True,scopes=set()))
    assert denied.get('/iphone/api/activities',params={'limit':2,'cursor':cursor}).status_code == 403


def apps_tools_app(tmp_path, devices, with_context=True):
    tools=ToolRegistry(SimpleNamespace(autonomy_mode='ask',data_dir=tmp_path))
    integrations=IntegrationRegistry()
    memory=MemoryStore(tmp_path/'memory.sqlite3')
    app=FastAPI()
    if with_context: app.add_middleware(ContextMiddleware)
    app.include_router(apps_tools_router({'device_registry':devices,'tools':tools,'integrations':integrations,'memory':memory}))
    return TestClient(app)


def test_apps_tools_requires_trusted_active_authorized_device(tmp_path):
    assert apps_tools_app(tmp_path/'a',Devices(active=True,scopes={'device:read'}),False).get('/iphone/api/apps-tools/tools').status_code == 401
    assert apps_tools_app(tmp_path/'b',Devices(active=False,scopes={'device:read'})).get('/iphone/api/apps-tools/tools').status_code == 401
    assert apps_tools_app(tmp_path/'c',Devices(active=True,scopes=set())).get('/iphone/api/apps-tools/tools').status_code == 403


def test_apps_tools_detail_not_found_is_safe(tmp_path):
    client=apps_tools_app(tmp_path,Devices(active=True,scopes={'device:read'}))
    assert client.get('/iphone/api/apps-tools/tools/missing').status_code == 404
    assert client.get('/iphone/api/apps-tools/apps/missing').status_code == 404


def test_activities_transport_rejects_out_of_bounds_inputs(tmp_path):
    client,_=activities_app(tmp_path,Devices(active=True,scopes={'activities:read'}))
    assert client.get('/iphone/api/activities?limit=0').status_code == 422
    assert client.get('/iphone/api/activities?limit=201').status_code == 422
    assert client.get('/iphone/api/activities',params={'category':'x'*101}).status_code == 422
    assert client.get('/iphone/api/activities',params={'status':'x'*81}).status_code == 422
    assert client.get('/iphone/api/activities',params={'cursor':'x'*769}).status_code == 422


def test_apps_tools_transport_rejects_oversized_identifiers(tmp_path):
    client=apps_tools_app(tmp_path,Devices(active=True,scopes={'device:read'}))
    assert client.get('/iphone/api/apps-tools/tools/' + ('x'*201)).status_code == 422
    assert client.get('/iphone/api/apps-tools/apps/' + ('x'*201)).status_code == 422
