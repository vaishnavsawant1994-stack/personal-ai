from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from devices.continuity import ContinuityService
from devices.continuity_sync import ContinuitySync
from devices.registry import DeviceRegistry
from future_intelligence.multimodal import WorldUnderstanding
from security.pwa_sessions import PwaSessionStore
from server.continuity_sync_api import continuity_sync_router
from server.pwa_session_middleware import PwaSessionMiddleware


class Gate:
    def decision(self, phase):
        assert phase in {'p7', 'p8'}
        return SimpleNamespace(allowed=True, reason='ok')


class Operations:
    def operation(self, operation_id):
        if operation_id != 'op-1':
            return None
        return {
            'operation_id': 'op-1', 'plan_id': 'plan-1', 'status': 'waiting_approval',
            'outcome_state': 'DISPATCHED', 'current_step': 1,
            'risk_summary': {'highest_risk': 'external_side_effect'},
            'source_refs': [], 'created_at': '2026-09-16T00:00:00+00:00',
            'updated_at': '2026-09-16T00:01:00+00:00', 'completed_at': None,
            'approval_id': 'NEVER-LEAK', 'parameters': {'token': 'NEVER-LEAK'},
        }


class Events:
    def __init__(self):
        self.items = []

    def emit(self, event, **payload):
        self.items.append({'event': event, **payload})


def fixture(tmp_path, *, events=None):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    first, _ = registry.enroll('first', 'web-pwa')
    second, _ = registry.enroll('second', 'ios-pwa')
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3', events=events)
    world = WorldUnderstanding(gate=Gate(), path=tmp_path / 'world.sqlite3', device_registry=registry)
    sync = ContinuitySync(
        continuity, gate=Gate(), device_registry=registry, security_epoch_provider=lambda: 9,
        operations=Operations(), world=world, events=events,
    )
    return registry, first, second, continuity, world, sync


def _event(event_id='e1', sequence=1, payload=None, kind='user_message'):
    return {
        'client_event_id': event_id,
        'client_sequence': sequence,
        'kind': kind,
        'payload': payload or {'text': 'hello'},
    }


def _api(tmp_path):
    registry, first, second, continuity, world, sync = fixture(tmp_path)
    sessions = PwaSessionStore(tmp_path / 'sessions.sqlite3')
    token, session = sessions.issue(first['id'])
    app = FastAPI()
    app.include_router(continuity_sync_router({'continuity_sync': sync}))
    app.add_middleware(PwaSessionMiddleware, sessions=sessions, device_registry=registry, cookie_max_age=3600)
    client = TestClient(app, base_url='https://testserver')
    cookies = {'pa_device': first['id'], 'pa_session': token}
    return client, cookies, registry, sessions, session, first, second, continuity, world, sync


def test_expired_and_mismatched_sessions_fail_closed(tmp_path):
    client, cookies, _, sessions, session, _, second, _, _, _ = _api(tmp_path)
    wrong_device = dict(cookies)
    wrong_device['pa_device'] = second['id']
    assert client.get('/iphone/api/continuity/status', cookies=wrong_device).status_code == 401

    malformed = dict(cookies)
    malformed['pa_device'] = 'forged-device-id'
    assert client.get('/iphone/api/continuity/status', cookies=malformed).status_code == 401

    with sqlite3.connect(sessions.path) as con:
        con.execute('UPDATE pwa_sessions SET expires_at=0 WHERE id=?', (session.id,))
    assert client.get('/iphone/api/continuity/status', cookies=cookies).status_code == 401


def test_sensitive_p7_reference_requires_existing_sensitive_scope(tmp_path):
    registry, first, _, continuity, world, sync = fixture(tmp_path)
    observation = world.ingest(
        'document', {'text': 'SENSITIVE-RAW'}, source='fixture', source_event_id='sensitive-1',
        device_id=first['id'], privacy_classification='sensitive',
    )
    with pytest.raises(KeyError, match='restricted'):
        sync.observation_status(observation['id'], device_id=first['id'], session_id='s1')

    registry.set_permissions(first['id'], DeviceRegistry.DEFAULT_SCOPES | {'memory:sensitive'})
    projected = sync.observation_status(observation['id'], device_id=first['id'], session_id='s1')
    assert projected['observation_id'] == observation['id']
    assert 'payload' not in projected
    assert 'SENSITIVE-RAW' not in str(projected)


def test_memory_and_operation_refs_preserve_existing_scope_authority(tmp_path):
    registry, first, _, continuity, _, sync = fixture(tmp_path)
    thread = continuity.create_thread('Scoped', device_id=first['id'])

    registry.set_permissions(first['id'], {'ai:chat'})
    with pytest.raises(PermissionError, match='memory'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=9, thread_id=thread,
            events=[_event('memory-1', 1, {'source_refs': ['memory:item-1']}, 'context_ref')],
        )
    with pytest.raises(PermissionError, match='operation|workflow'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=9, thread_id=thread,
            events=[_event('operation-1', 1, {'source_refs': ['operation:op-1']}, 'context_ref')],
        )
    assert continuity.events_for_thread(thread) == []


def test_payload_shape_numeric_and_batch_attacks_fail_closed(tmp_path):
    _, first, _, continuity, _, sync = fixture(tmp_path)
    thread = continuity.create_thread('Adversarial', device_id=first['id'])

    deep = {'leaf': 'x'}
    for _ in range(ContinuitySync.MAX_DEPTH + 2):
        deep = {'nested': deep}
    payloads = [
        deep,
        {'text': 'x' * (ContinuitySync.MAX_STRING_CHARS + 1)},
        {'items': list(range(129))},
        {f'k{i}': i for i in range(65)},
        {'number': float('nan')},
        {'number': float('inf')},
        {'number': float('-inf')},
    ]
    for index, payload in enumerate(payloads, start=1):
        with pytest.raises(ValueError):
            sync.reconcile(
                device_id=first['id'], session_id='s1', security_epoch=9, thread_id=thread,
                events=[_event(f'attack-{index}', index, payload)],
            )
    with pytest.raises(ValueError, match='batch'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=9, thread_id=thread,
            events=[_event(f'batch-{i}', i + 1) for i in range(ContinuitySync.MAX_BATCH_EVENTS + 1)],
        )
    assert continuity.events_for_thread(thread) == []


def test_closed_and_unknown_threads_fail_closed(tmp_path):
    _, first, _, continuity, _, sync = fixture(tmp_path)
    with pytest.raises(KeyError, match='thread'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=9,
            thread_id='does-not-exist', events=[],
        )
    thread = continuity.create_thread('Closed', device_id=first['id'])
    assert continuity.archive_thread(thread) is True
    with pytest.raises(KeyError, match='thread'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=9,
            thread_id=thread, events=[],
        )


def test_server_projection_is_bounded_even_when_history_is_large(tmp_path):
    _, first, _, continuity, _, sync = fixture(tmp_path)
    thread = continuity.create_thread('Large', device_id=first['id'])
    for index in range(510):
        continuity.append(thread, device_id=first['id'], kind='user_message', payload={'text': f'message-{index}'})
    result = sync.reconcile(
        device_id=first['id'], session_id='s1', security_epoch=9,
        thread_id=thread, events=[], limit=9999,
    )
    assert len(result['server_events']) == ContinuitySync.MAX_SERVER_EVENTS


def test_continuity_events_and_sync_audit_do_not_copy_message_payload(tmp_path):
    events = Events()
    _, first, second, continuity, _, sync = fixture(tmp_path, events=events)
    thread = continuity.create_thread('Safe audit', device_id=first['id'])
    secret_text = 'LEAK-CONTENT-MUST-STAY-IN-CANONICAL-CONVERSATION'
    sync.reconcile(
        device_id=first['id'], session_id='s1', security_epoch=9, thread_id=thread,
        events=[_event('safe-audit-1', 1, {'text': secret_text})],
    )
    sync.handoff(device_id=first['id'], session_id='s1', to_device=second['id'], thread_id=thread)
    event_text = json.dumps(events.items, sort_keys=True)
    assert secret_text not in event_text
    assert 'authorization' not in event_text.lower()
    assert 'cookie' not in event_text.lower()
    assert any(row['event'] == 'continuity.sync' for row in events.items)
    assert any(row['event'] == 'continuity.handoff' for row in events.items)
