from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from devices.registry import DeviceRegistry
from memory.store import MemoryStore
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.activities_api import activities_router


def app_for(tmp_path, scopes):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, _ = registry.enroll('Owner browser', 'web-pwa')
    registry.set_permissions(device['id'], scopes)
    memory = MemoryStore(tmp_path / 'memory.sqlite3')
    memory.audit('tool', 'execute', {'tool': 'safe-tool', 'ok': True})
    app = FastAPI(); app.include_router(activities_router({'device_registry': registry, 'memory': memory}))
    return app, registry, device['id']


def get_with_context(app, device_id, session_id='session-1'):
    token = set_trusted_request(TrustedRequestContext(device_id, session_id, 123.0))
    try:
        return TestClient(app).get('/iphone/api/activities')
    finally:
        reset_trusted_request(token)


def test_owner_device_with_activities_read_is_allowed(tmp_path):
    app, _, device_id = app_for(tmp_path, {'activities:read'})
    response = get_with_context(app, device_id)
    assert response.status_code == 200
    assert len(response.json()['activities']) == 1


def test_chat_only_device_cannot_read_activities(tmp_path):
    app, _, device_id = app_for(tmp_path, {'ai:chat'})
    assert get_with_context(app, device_id).status_code == 403


def test_untrusted_and_revoked_devices_are_denied(tmp_path):
    app, registry, device_id = app_for(tmp_path, {'activities:read'})
    assert TestClient(app).get('/iphone/api/activities').status_code == 401
    registry.revoke(device_id)
    assert get_with_context(app, device_id).status_code == 401


def test_cross_device_context_without_scope_is_denied(tmp_path):
    app, registry, _ = app_for(tmp_path, {'activities:read'})
    other, _ = registry.enroll('Other trusted browser', 'web-pwa')
    registry.set_permissions(other['id'], {'ai:chat'})
    assert get_with_context(app, other['id']).status_code == 403
