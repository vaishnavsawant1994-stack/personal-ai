"""A revoked connector must not keep calling the provider or become healthy again."""

from __future__ import annotations

import json

import pytest

from integrations.adapters import GmailAdapter, IntegrationError
from integrations.contracts import gmail_manifest
from integrations.gateway import ConnectorError, ConnectorGateway
from integrations.oauth import OAuthAccountManager
from integrations.registry import Integration, IntegrationRegistry
from integrations.state import ConnectorStateStore


class Vault:
    def __init__(self):
        self.d = {}

    def set(self, key, value):
        self.d[key] = value

    def get(self, key, default=None):
        return self.d.get(key, default)

    def delete(self, key):
        self.d.pop(key, None)


class Response:
    def __init__(self):
        self.status_code = 200
        self.headers = {}
        self.content = b'{"ok":1}'

    def json(self):
        return {'ok': 1}


class Session:
    def __init__(self):
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return Response()


def test_gateway_does_not_call_or_heal_a_revoked_connector(tmp_path):
    store = ConnectorStateStore(tmp_path / 'connectors.sqlite3', vault=Vault())
    store.set_health('gmail', 'revoked', revocation_status='local_revoked')
    session = Session()
    gateway = ConnectorGateway(store, session=session, sleep=lambda _: None)
    with pytest.raises(ConnectorError, match='revoked'):
        gateway.request(type('A', (), {'base_url': 'https://provider.test', 'granted_scopes': None})(), gmail_manifest().operation('gmail.read'), 'GET', 'x')
    assert session.calls == 0
    assert store.health('gmail')['state'] == 'revoked'


def test_healthcheck_does_not_resurrect_a_revoked_connector(tmp_path):
    store = ConnectorStateStore(tmp_path / 'connectors.sqlite3', vault=Vault())
    store.set_health('gmail', 'revoked', revocation_status='local_revoked')
    calls = []
    registry = IntegrationRegistry(state_store=store)
    registry.register(Integration('gmail', 'Gmail', set(), lambda: calls.append(True) or True))
    healthy, state = registry._health(registry.get('gmail'))
    assert calls == []
    assert healthy is False
    assert state['state'] == 'revoked'


def test_unlink_drops_the_live_token(monkeypatch):
    vault = Vault()
    vault.set('oauth:google', json.dumps({'access_token': 'secret-token'}))
    manager = OAuthAccountManager(vault)
    adapter = GmailAdapter('secret-token')
    manager.bind_live({'gmail': adapter})
    result = manager.unlink('google', attempt_provider_revocation=False)
    assert result['revoked'] is True
    assert adapter.token is None
    assert vault.get('oauth:google') is None

    def fail(*args, **kwargs):
        raise AssertionError('revoked token was sent')

    monkeypatch.setattr('integrations.adapters.requests.request', fail)
    with pytest.raises(IntegrationError, match='revoked'):
        adapter.request('GET', 'users/me/profile')
