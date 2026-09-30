from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.everyday_intelligence_api import everyday_intelligence_router


class Registry:
    def __init__(self):
        self.allowed = True

    def authenticate(self, device_id, token):
        return device_id == 'owner-device' and token == 'owner-token'

    def authorize(self, device_id, scope):
        return self.allowed and device_id == 'owner-device' and scope == 'ai:chat'


class Everyday:
    def __init__(self):
        self.calls = []
        self.records = {}

    def add(self, kind, title, **kwargs):
        self.calls.append((kind, title, kwargs))
        self.records['item-1'] = {'id': 'item-1', 'kind': kind, 'title': title, **kwargs}
        return 'item-1'

    def get(self, item_id):
        return self.records.get(item_id)


def client_for_today():
    registry = Registry()
    everyday = Everyday()
    app = FastAPI()
    app.include_router(everyday_intelligence_router({
        'device_registry': registry, 'everyday_intelligence': everyday,
    }))
    client = TestClient(app)
    return client, registry, everyday


def auth():
    return {'pa_device': 'owner-device', 'pa_token': 'owner-token'}


def test_today_item_creation_requires_trusted_owner_and_chat_permission():
    client, registry, everyday = client_for_today()
    payload = {'category': 'task', 'title': 'Finish review',
               'due_at': '2026-09-30', 'timezone': 'Europe/Berlin'}
    assert client.post('/iphone/api/everyday/items', json=payload).status_code == 401
    registry.allowed = False
    assert client.post('/iphone/api/everyday/items', cookies=auth(), json=payload).status_code == 403
    assert everyday.calls == []


def test_today_meeting_is_real_durable_everyday_commitment():
    client, _, everyday = client_for_today()
    result = client.post('/iphone/api/everyday/items', cookies=auth(), json={
        'category': 'meeting', 'title': '  Design review  ',
        'due_at': '2026-09-30T11:30:00+02:00', 'timezone': 'Europe/Berlin',
    })
    assert result.status_code == 201, result.text
    assert result.json()['item']['title'] == 'Design review'
    assert everyday.calls == [(
        'commitment', 'Design review',
        {'due_at': '2026-09-30T11:30:00+02:00',
         'context': 'personal-ai:today:meeting',
         'source': 'today_ui', 'timezone_name': 'Europe/Berlin'},
    )]


def test_today_rejects_untrusted_categories_malformed_dates_and_blank_titles():
    client, _, everyday = client_for_today()
    base = {'title': 'Review', 'due_at': '2026-09-30',
            'timezone': 'Europe/Berlin'}
    for payload in [
        {**base, 'category': 'fake'},
        {**base, 'category': 'meeting'},
        {**base, 'category': 'task', 'due_at': '2026-00-00'},
        {**base, 'category': 'task', 'title': '   '},
        {**base, 'category': 'meeting', 'due_at': '2026-09-30T11:30:00'},
    ]:
        assert client.post('/iphone/api/everyday/items', cookies=auth(), json=payload).status_code == 422
    assert everyday.calls == []
