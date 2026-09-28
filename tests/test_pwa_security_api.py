from __future__ import annotations

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from security.owner_access import OwnerAccessStore
from security.pwa_sessions import PwaSessionStore
from server.pwa_security import pwa_security_router
from server.pwa_session_middleware import PwaSessionMiddleware


class Devices:
    def is_active(self, device_id):
        return device_id == 'device-1'


class TurnProbe:
    def __init__(self):
        self.cancelled_sessions = []

    def cancel_session_turns(self, session_id, *, reason='session_revoked'):
        self.cancelled_sessions.append((session_id, reason))
        return 1


class AutomationProbe:
    def __init__(self):
        self.cancelled_sessions = []

    def cancel_session_runs(self, session_id, *, reason='session_revoked'):
        self.cancelled_sessions.append((session_id, reason))
        return 1


def make_client(tmp_path):
    sessions = PwaSessionStore(tmp_path / 'pwa-sessions.sqlite3', ttl_seconds=600)
    owner = OwnerAccessStore(tmp_path / 'owner-access.sqlite3')
    owner.set_password('correct horse battery staple')
    devices = Devices()
    app = FastAPI()
    app.add_middleware(PwaSessionMiddleware, sessions=sessions, device_registry=devices, cookie_max_age=600)

    @app.post('/iphone/api/access/password/login')
    def login(response: Response):
        response.set_cookie('pa_device', 'device-1', secure=True, httponly=True, samesite='strict', path='/iphone')
        response.set_cookie('pa_token', 'device-bearer', secure=True, httponly=True, samesite='strict', path='/iphone')
        return {'ok': True}

    turns = TurnProbe()
    automations = AutomationProbe()
    app.include_router(pwa_security_router({'pwa_sessions': sessions, 'owner_access': owner, 'executor': turns, 'automations': automations}))
    return TestClient(app, base_url='https://testserver'), sessions, automations, turns


def test_password_reauth_updates_only_current_session(tmp_path):
    client, sessions, _, _ = make_client(tmp_path)
    client.post('/iphone/api/access/password/login')
    current = client.get('/iphone/api/sessions').json()['current_session_id']
    before = sessions.get(current).reauthenticated_at

    bad = client.post('/iphone/api/access/reauth/password', json={'password': 'wrong'})
    assert bad.status_code == 401

    good = client.post('/iphone/api/access/reauth/password', json={'password': 'correct horse battery staple'})
    assert good.status_code == 200
    assert sessions.get(current).reauthenticated_at >= before


def test_session_list_and_revoke_others_are_device_scoped(tmp_path):
    client, sessions, _, _ = make_client(tmp_path)
    client.post('/iphone/api/access/password/login')
    current = client.get('/iphone/api/sessions').json()['current_session_id']
    _, other = sessions.issue('device-1')
    sessions.issue('device-2')

    listing = client.get('/iphone/api/sessions').json()
    ids = {row['id'] for row in listing['sessions']}
    assert current in ids and other.id in ids

    result = client.post('/iphone/api/sessions/revoke-others').json()
    assert result['revoked'] == 1
    assert sessions.get(current) is not None
    assert sessions.get(other.id) is None
    assert len(sessions.active_for_device('device-2')) == 1


def test_cannot_revoke_session_from_another_device(tmp_path):
    client, sessions, _, _ = make_client(tmp_path)
    client.post('/iphone/api/access/password/login')
    _, foreign = sessions.issue('device-2')

    response = client.post(f'/iphone/api/sessions/{foreign.id}/revoke')
    assert response.status_code == 404
    assert sessions.get(foreign.id) is not None


def test_stage8_session_revocation_cancels_bound_automation(tmp_path):
    client, sessions, automations, turns = make_client(tmp_path)
    client.post('/iphone/api/access/password/login')
    current = client.get('/iphone/api/sessions').json()['current_session_id']
    _, other = sessions.issue('device-1')

    response = client.post(f'/iphone/api/sessions/{other.id}/revoke')
    assert response.status_code == 200
    assert response.json()['cancelled_turns'] == 1
    assert response.json()['cancelled_workflows'] == 1
    assert turns.cancelled_sessions == [(other.id, 'session_revoked')]
    assert automations.cancelled_sessions == [(other.id, 'session_revoked')]
    assert sessions.get(current) is not None
