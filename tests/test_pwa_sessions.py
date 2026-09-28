from __future__ import annotations

import time

from security.pwa_sessions import PwaSessionStore


def test_pwa_session_token_is_opaque_and_device_bound(tmp_path):
    path = tmp_path / 'pwa-sessions.sqlite3'
    store = PwaSessionStore(path, ttl_seconds=600)
    token, session = store.issue('device-1')

    assert token not in path.read_bytes().decode('latin1', errors='ignore')
    assert store.authenticate(token, 'device-1').id == session.id
    assert store.authenticate(token, 'device-2') is None


def test_pwa_session_survives_store_restart_and_revokes_immediately(tmp_path):
    path = tmp_path / 'pwa-sessions.sqlite3'
    first = PwaSessionStore(path, ttl_seconds=600)
    token, session = first.issue('device-1')

    restarted = PwaSessionStore(path, ttl_seconds=600)
    assert restarted.authenticate(token, 'device-1').id == session.id
    assert restarted.revoke(session.id) is True
    assert PwaSessionStore(path, ttl_seconds=600).authenticate(token, 'device-1') is None


def test_device_revocation_invalidates_all_browser_sessions(tmp_path):
    store = PwaSessionStore(tmp_path / 'pwa-sessions.sqlite3', ttl_seconds=600)
    token_a, session_a = store.issue('device-1')
    token_b, session_b = store.issue('device-1')
    token_c, session_c = store.issue('device-2')

    assert store.revoke_device('device-1') == 2
    assert store.authenticate(token_a, 'device-1') is None
    assert store.authenticate(token_b, 'device-1') is None
    assert store.authenticate(token_c, 'device-2').id == session_c.id


def test_reauthentication_timestamp_is_durable_and_session_scoped(tmp_path):
    path = tmp_path / 'pwa-sessions.sqlite3'
    store = PwaSessionStore(path, ttl_seconds=600)
    token_a, session_a = store.issue('device-1', reauthenticated=False)
    token_b, session_b = store.issue('device-1', reauthenticated=False)

    assert store.authenticate(token_a, 'device-1').reauthenticated_at is None
    stamp = time.time()
    assert store.mark_reauthenticated(session_a.id, at=stamp) is True

    restarted = PwaSessionStore(path, ttl_seconds=600)
    assert restarted.authenticate(token_a, 'device-1').reauthenticated_at == stamp
    assert restarted.authenticate(token_b, 'device-1').reauthenticated_at is None


def test_revoke_all_sessions(tmp_path):
    store = PwaSessionStore(tmp_path / 'pwa-sessions.sqlite3', ttl_seconds=600)
    first, _ = store.issue('device-1')
    second, _ = store.issue('device-2')

    assert store.revoke_all() == 2
    assert store.authenticate(first, 'device-1') is None
    assert store.authenticate(second, 'device-2') is None
