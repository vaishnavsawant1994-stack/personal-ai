"""Hostile proof that the three deferred API gaps are actually closed."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from devices.registry import DeviceRegistry
from server.capability_console import capability_console_router
from tests.test_p2_control_api import auth_headers, build_client
from tests.test_p3_iphone_pwa import make_client


def test_workflow_list_hides_another_devices_steps(tmp_path):
    client, _, registry = build_client(tmp_path)
    owner, owner_token = registry.enroll('Owner phone', 'ios')
    registry.set_permissions(owner['id'], registry.OWNER_SCOPES)
    other, other_token = registry.enroll('Other phone', 'android')
    registry.set_permissions(other['id'], registry.OWNER_SCOPES)
    narrow, narrow_token = registry.enroll('Narrow', 'android')
    registry.set_permissions(narrow['id'], {'ai:chat'})

    secret = 'do not show this prompt to another device'
    created = client.post(
        '/workflows/create',
        json={'title': 'Private', 'trigger': {'type': 'manual'}, 'steps': [{'kind': 'prompt', 'prompt': secret}]},
        headers=auth_headers(owner, owner_token),
    )
    assert created.status_code == 200
    workflow_id = created.json()['workflow_id']

    own = client.get('/workflows', headers=auth_headers(owner, owner_token))
    assert own.status_code == 200
    assert any(row['id'] == workflow_id and secret in str(row) for row in own.json())

    foreign = client.get('/workflows', headers=auth_headers(other, other_token))
    assert foreign.status_code == 200
    assert foreign.json() == []
    assert secret not in foreign.text

    assert client.get('/workflows', headers=auth_headers(narrow, narrow_token)).status_code == 403
    assert client.get('/workflows').status_code == 401

    leaked = client.get('/workflows', headers=auth_headers(owner, owner_token)).json()
    assert all(row.get('created_device_id') == owner['id'] for row in leaked)


def test_capability_status_requires_a_device_session(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    app = FastAPI()
    app.include_router(capability_console_router({
        'device_registry': registry,
        'future_intelligence': type('Future', (), {'status': lambda self: {'p4': {'activation': 'gated'}}})(),
        'memory': {'private': 'must-not-leak'},
    }))
    client = TestClient(app)
    assert client.get('/capabilities/api/status').status_code == 401

    device, token = registry.enroll('Reader', 'ios')
    denied, denied_token = registry.enroll('Denied', 'ios')
    registry.set_permissions(denied['id'], {'ai:chat'})
    headers = {'Authorization': f'Bearer {token}', 'X-Device-Id': device['id']}
    ok = client.get('/capabilities/api/status', headers=headers)
    assert ok.status_code == 200
    body = ok.json()
    assert body['runtime_ready'] is True
    assert 'must-not-leak' not in ok.text
    assert 'private' not in body
    assert client.get('/capabilities/api/status', headers={'Authorization': 'Bearer wrong', 'X-Device-Id': device['id']}).status_code == 401
    assert client.get(
        '/capabilities/api/status',
        headers={'Authorization': f'Bearer {denied_token}', 'X-Device-Id': denied['id']},
    ).status_code == 403


def test_iphone_logout_revokes_only_that_device_and_its_server_session(tmp_path):
    client, runtime = make_client(tmp_path, allow_insecure=True, server_sessions=True)
    enrolled = client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code', 'name': 'This phone'})
    assert enrolled.status_code == 200
    device_id = enrolled.json()['device_id']
    runtime['pwa_sessions'].issue(device_id)
    other, _token = runtime['device_registry'].enroll('Other phone', 'ios-pwa')
    runtime['pwa_sessions'].issue(other['id'])

    bare = TestClient(client.app, base_url='https://testserver')
    assert bare.post('/iphone/api/logout').status_code == 401
    assert runtime['device_registry'].is_active(device_id)

    logged_out = client.post('/iphone/api/logout')
    assert logged_out.status_code == 200
    assert logged_out.json()['revoked'] is True
    assert runtime['device_registry'].is_active(device_id) is False
    assert runtime['pwa_sessions'].active_for_device(device_id) == []
    assert client.get('/iphone/api/status').status_code == 401
    assert runtime['device_registry'].is_active(other['id'])
    assert runtime['pwa_sessions'].active_for_device(other['id'])
