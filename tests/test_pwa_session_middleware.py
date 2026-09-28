from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from security.pwa_sessions import PwaSessionStore
from security.request_context import current_trusted_request
from server.pwa_session_middleware import PwaSessionMiddleware


class Devices:
    def __init__(self):
        self.active = {'device-1'}

    def is_active(self, device_id):
        return device_id in self.active


def make_client(tmp_path):
    sessions = PwaSessionStore(tmp_path / 'pwa-sessions.sqlite3', ttl_seconds=600)
    devices = Devices()
    app = FastAPI()
    app.add_middleware(
        PwaSessionMiddleware,
        sessions=sessions,
        device_registry=devices,
        cookie_max_age=600,
    )

    @app.post('/iphone/api/access/password/login')
    def login(response: Response):
        response.set_cookie('pa_device', 'device-1', httponly=True, secure=True, samesite='strict', path='/iphone')
        response.set_cookie('pa_token', 'device-bearer', httponly=True, secure=True, samesite='strict', path='/iphone')
        return {'ok': True}

    @app.get('/iphone/api/protected')
    def protected(request: Request):
        context = current_trusted_request()
        return {
            'session_id': context.session_id if context else None,
            'device_id': context.device_id if context else None,
            'reauthenticated_at': context.reauthenticated_at if context else None,
        }

    @app.post('/iphone/api/logout')
    def logout(response: Response):
        response.delete_cookie('pa_device', path='/iphone')
        response.delete_cookie('pa_token', path='/iphone')
        return {'ok': True}

    return TestClient(app, base_url='https://testserver'), sessions, devices


def test_device_bearer_alone_cannot_access_protected_pwa_api(tmp_path):
    client, _, _ = make_client(tmp_path)
    client.cookies.set('pa_device', 'device-1', path='/iphone')
    client.cookies.set('pa_token', 'stolen-device-bearer', path='/iphone')

    response = client.get('/iphone/api/protected')
    assert response.status_code == 401
    assert response.json()['detail']['code'] == 'session_expired'


def test_login_issues_server_session_and_binds_request_context(tmp_path):
    client, sessions, _ = make_client(tmp_path)
    login = client.post('/iphone/api/access/password/login')
    assert login.status_code == 200
    assert client.cookies.get('pa_session')

    protected = client.get('/iphone/api/protected')
    assert protected.status_code == 200
    payload = protected.json()
    assert payload['device_id'] == 'device-1'
    assert payload['session_id']
    assert payload['reauthenticated_at'] is not None
    assert sessions.get(payload['session_id']) is not None


def test_logout_revokes_server_side_session(tmp_path):
    client, sessions, _ = make_client(tmp_path)
    client.post('/iphone/api/access/password/login')
    protected = client.get('/iphone/api/protected').json()
    session_id = protected['session_id']

    logout = client.post('/iphone/api/logout')
    assert logout.status_code == 200
    assert sessions.get(session_id) is None
    assert client.get('/iphone/api/protected').status_code == 401


def test_device_revocation_invalidates_existing_browser_session(tmp_path):
    client, sessions, devices = make_client(tmp_path)
    client.post('/iphone/api/access/password/login')
    session_id = client.get('/iphone/api/protected').json()['session_id']
    devices.active.remove('device-1')

    response = client.get('/iphone/api/protected')
    assert response.status_code == 401
    assert response.json()['detail']['code'] == 'device_revoked'
    assert sessions.get(session_id) is None
