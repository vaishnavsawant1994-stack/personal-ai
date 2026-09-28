import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from devices.presence_projection import DevicesPresenceProjection
from devices.registry import DeviceRegistry
from devices.gateway import DeviceCommand, DeviceGateway
from core.events import EventBus
from security.pwa_sessions import PwaSessionStore
from security.request_context import TrustedRequestContext
import server.devices_presence_api as devices_api
from server.devices_presence_api import devices_presence_router


class Gateway:
    def __init__(self, online=()):
        self.ids = list(online)

    def online(self):
        return list(self.ids)


def test_presence_projection_uses_live_gateway_and_redacts_metadata(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, _ = registry.enroll('<script>alert(1)</script>', 'ios')
    registry.set_metadata(device['id'], 'push.apns.token', 'Authorization: Bearer SECRET')
    registry.set_metadata(device['id'], 'label', 'https://x.test/?token=SECRET')
    projection = DevicesPresenceProjection(registry, Gateway([device['id']]))
    item = projection.detail(device['id'])
    assert item['trust_state'] == 'trusted'
    assert item['presence_state'] == 'online'
    assert item['connected'] is True
    assert 'push.apns.token' not in item['metadata']
    assert 'SECRET' not in repr(item)
    assert '<script>' in item['display_name']


def test_enrolled_device_is_not_claimed_online_without_live_evidence(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, _ = registry.enroll('Phone', 'ios')
    item = DevicesPresenceProjection(registry, Gateway()).detail(device['id'])
    assert item['trust_state'] == 'trusted'
    assert item['presence_state'] == 'unknown'
    assert item['connected'] is False


def test_revoked_device_is_never_presented_connected(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, _ = registry.enroll('Phone', 'ios')
    registry.revoke(device['id'])
    item = DevicesPresenceProjection(registry, Gateway([device['id']])).detail(device['id'])
    assert item['trust_state'] == 'revoked'
    assert item['presence_state'] == 'revoked'
    assert item['connected'] is False


def test_nested_metadata_is_redacted_safe_metadata_survives_and_registry_is_unchanged(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, _ = registry.enroll('Desktop', 'windows')
    registry.set_metadata(device['id'], 'safe.label', 'Office desktop')
    registry.set_metadata(device['id'], 'provider.note', 'Authorization: Bearer SUPERSECRET123')
    before = registry.list()
    item = DevicesPresenceProjection(registry, Gateway()).detail(device['id'])
    after = registry.list()
    assert item['metadata']['safe.label'] == 'Office desktop'
    assert 'SUPERSECRET123' not in repr(item)
    assert before == after


def test_projection_is_bounded_and_unknown_detail_is_none(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    for index in range(205):
        registry.enroll(f'Device {index}', 'test')
    projection = DevicesPresenceProjection(registry, Gateway())
    assert len(projection.list()) == projection.MAX_DEVICES
    assert projection.detail('missing-device') is None
    assert projection.detail('x' * 201) is None


def test_devices_presence_api_requires_active_scoped_trusted_device(tmp_path, monkeypatch):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    caller, _ = registry.enroll('Owner', 'ios-pwa')
    target, _ = registry.enroll('Desktop', 'windows')
    current = {'value': None}
    monkeypatch.setattr(devices_api, 'current_trusted_request', lambda: current['value'])
    app = FastAPI()
    app.include_router(devices_presence_router({'device_registry': registry, 'device_gateway': Gateway([target['id']])}))
    client = TestClient(app)

    assert client.get('/iphone/api/devices-presence').status_code == 401
    current['value'] = TrustedRequestContext(device_id=caller['id'], session_id='s1')
    response = client.get('/iphone/api/devices-presence')
    assert response.status_code == 200
    assert any(row['device_id'] == target['id'] and row['presence_state'] == 'online' for row in response.json()['devices'])

    registry.set_permissions(caller['id'], {'ai:chat'})
    assert client.get('/iphone/api/devices-presence').status_code == 403

    registry.set_permissions(caller['id'], {'device:read'})
    registry.revoke(caller['id'])
    assert client.get('/iphone/api/devices-presence').status_code == 401



def test_owner_revocation_requires_admin_and_fresh_reauthentication(tmp_path, monkeypatch):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    caller, _ = registry.enroll('Owner', 'ios-pwa')
    target, _ = registry.enroll('Desktop', 'windows')
    registry.set_permissions(caller['id'], {'device:read', 'device:admin'})
    sessions = PwaSessionStore(tmp_path / 'pwa-sessions.sqlite3')
    _, target_session = sessions.issue(target['id'])
    gateway = DeviceGateway(registry, EventBus())
    current = {'value': TrustedRequestContext(device_id=caller['id'], session_id='owner-session', reauthenticated_at=None)}
    monkeypatch.setattr(devices_api, 'current_trusted_request', lambda: current['value'])
    app = FastAPI()
    app.include_router(devices_presence_router({
        'device_registry': registry, 'device_gateway': gateway, 'pwa_sessions': sessions,
    }))
    client = TestClient(app)

    assert client.delete(f"/iphone/api/devices-presence/{target['id']}").status_code == 403
    current['value'] = TrustedRequestContext(
        device_id=caller['id'], session_id='owner-session', reauthenticated_at=time.time() - 999,
    )
    assert client.delete(f"/iphone/api/devices-presence/{target['id']}").status_code == 403

    current['value'] = TrustedRequestContext(
        device_id=caller['id'], session_id='owner-session', reauthenticated_at=time.time(),
    )
    response = client.delete(f"/iphone/api/devices-presence/{target['id']}")
    assert response.status_code == 200
    assert response.json()['trust_state'] == 'revoked'
    assert response.json()['revoked_sessions'] == 1
    assert registry.is_active(target['id']) is False
    assert sessions.get(target_session.id) is None


def test_revocation_rejects_unknown_target_and_revoked_caller(tmp_path, monkeypatch):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    caller, _ = registry.enroll('Owner', 'ios-pwa')
    registry.set_permissions(caller['id'], {'device:admin'})
    current = {'value': TrustedRequestContext(
        device_id=caller['id'], session_id='owner-session', reauthenticated_at=time.time(),
    )}
    monkeypatch.setattr(devices_api, 'current_trusted_request', lambda: current['value'])
    app = FastAPI()
    app.include_router(devices_presence_router({'device_registry': registry, 'device_gateway': Gateway()}))
    client = TestClient(app)

    assert client.delete('/iphone/api/devices-presence/not-a-device').status_code == 404
    registry.revoke(caller['id'])
    assert client.delete(f"/iphone/api/devices-presence/{caller['id']}").status_code == 401


def test_device_gateway_fails_closed_after_revocation_and_rejects_late_result(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, _ = registry.enroll('Desktop', 'windows')
    events = EventBus()
    gateway = DeviceGateway(registry, events)

    class Session:
        async def send_json(self, payload):
            self.payload = payload

    session = Session()
    gateway.connect(device['id'], session)
    assert gateway.online() == [device['id']]
    registry.revoke(device['id'])
    assert gateway.online() == []
    assert gateway.receive(device['id'], {'request_id': 'late', 'ok': True}) is False


def test_device_gateway_cannot_reconnect_revoked_device(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, _ = registry.enroll('Desktop', 'windows')
    registry.revoke(device['id'])
    gateway = DeviceGateway(registry, EventBus())
    try:
        gateway.connect(device['id'], object())
    except PermissionError:
        pass
    else:
        raise AssertionError('revoked device reconnected')
