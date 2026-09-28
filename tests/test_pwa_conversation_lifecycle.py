from __future__ import annotations

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from devices.continuity import ContinuityService
from security.pwa_sessions import PwaSessionStore
from server.pwa_conversations import pwa_conversation_router
from server.pwa_session_middleware import PwaSessionMiddleware


class Devices:
    def is_active(self, device_id):
        return device_id == 'device-1'


def make_client(tmp_path):
    sessions = PwaSessionStore(tmp_path / 'pwa-sessions.sqlite3', ttl_seconds=600)
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3')
    app = FastAPI()
    app.add_middleware(PwaSessionMiddleware, sessions=sessions, device_registry=Devices(), cookie_max_age=600)

    @app.post('/iphone/api/access/password/login')
    def login(response: Response):
        response.set_cookie('pa_device', 'device-1', secure=True, httponly=True, samesite='strict', path='/iphone')
        response.set_cookie('pa_token', 'device-token', secure=True, httponly=True, samesite='strict', path='/iphone')
        return {'ok': True}

    app.include_router(pwa_conversation_router({'continuity': continuity}))
    return TestClient(app, base_url='https://testserver'), continuity


def test_archive_and_export_conversation(tmp_path):
    client, continuity = make_client(tmp_path)
    client.post('/iphone/api/access/password/login')
    thread = continuity.create_thread('Owner conversation', device_id='device-1')
    continuity.append(thread, device_id='device-1', kind='user_message', payload={'text': 'hello'})

    export = client.get(f'/iphone/api/conversations/{thread}/export')
    assert export.status_code == 200
    assert 'attachment;' in export.headers['content-disposition']
    assert export.json()['events'][0]['payload']['text'] == 'hello'

    archived = client.post(f'/iphone/api/conversations/{thread}/archive')
    assert archived.status_code == 200
    assert archived.json()['status'] == 'archived'
    assert continuity.thread(thread)['closed_at'] is not None


def test_delete_conversation_requires_session_and_removes_state(tmp_path):
    client, continuity = make_client(tmp_path)
    thread = continuity.create_thread('Delete', device_id='device-1')
    assert client.delete(f'/iphone/api/conversations/{thread}').status_code == 401

    client.post('/iphone/api/access/password/login')
    deleted = client.delete(f'/iphone/api/conversations/{thread}')
    assert deleted.status_code == 200
    assert continuity.thread(thread) is None
