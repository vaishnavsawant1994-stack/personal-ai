from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from devices.continuity import ContinuityService
from devices.continuity_sync import ContinuitySync
from devices.registry import DeviceRegistry
from future_intelligence.everywhere import PersonalAIEverywhere
from future_intelligence.multimodal import WorldUnderstanding
from security.pwa_sessions import PwaSessionStore
from server.continuity_sync_api import continuity_sync_router
from server.pwa_session_middleware import PwaSessionMiddleware


NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)


class Gate:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def decision(self, phase):
        assert phase in {'p7', 'p8'}
        return SimpleNamespace(
            allowed=self.allowed,
            reason='prerequisites satisfied' if self.allowed else 'qualification prerequisites not proven: p3.continuity',
        )


class Operations:
    def __init__(self):
        self.value = {
            'operation_id': 'op-1', 'plan_id': 'plan-1', 'status': 'waiting_approval',
            'outcome_state': 'DISPATCHED', 'current_step': 1,
            'risk_summary': {'highest_risk': 'external_side_effect'},
            'source_refs': ['observation:obs-1'],
            'created_at': '2026-09-16T00:00:00+00:00',
            'updated_at': '2026-09-16T00:01:00+00:00', 'completed_at': None,
            'approval_id': 'MUST-NOT-LEAK', 'session_id': 'MUST-NOT-LEAK',
            'device_id': 'MUST-NOT-LEAK', 'parameters': {'token': 'MUST-NOT-LEAK'},
        }

    def operation(self, operation_id):
        return dict(self.value) if operation_id == 'op-1' else None


def fixture(tmp_path, *, gate=None):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    first, _ = registry.enroll('first', 'web-pwa')
    second, _ = registry.enroll('second', 'ios-pwa')
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3')
    world = WorldUnderstanding(
        gate=Gate(True), path=tmp_path / 'world.sqlite3', device_registry=registry, clock=lambda: NOW,
    )
    epoch = [7]
    sync = ContinuitySync(
        continuity,
        gate=gate or Gate(True),
        device_registry=registry,
        security_epoch_provider=lambda: epoch[0],
        operations=Operations(),
        world=world,
    )
    return registry, first, second, continuity, world, epoch, sync


def test_p8_gate_blocks_without_continuity_proof(tmp_path):
    _, first, _, _, _, _, sync = fixture(tmp_path, gate=Gate(False))
    with pytest.raises(PermissionError, match='p3.continuity'):
        sync.status(device_id=first['id'], session_id='s1')


def test_trusted_device_reconcile_is_idempotent_and_restart_safe(tmp_path):
    registry, first, _, continuity, world, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Shared', device_id=first['id'])
    body = {'client_event_id': 'client-event-1', 'client_sequence': 1, 'kind': 'user_message', 'payload': {'text': 'hello'}}
    first_result = sync.reconcile(
        device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread, events=[body],
    )
    assert first_result['accepted_client_event_ids'] == ['client-event-1']
    duplicate = sync.reconcile(
        device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread, events=[body],
    )
    assert duplicate['duplicate_client_event_ids'] == ['client-event-1']

    restarted = ContinuitySync(
        ContinuityService(tmp_path / 'continuity.sqlite3'), gate=Gate(True), device_registry=registry,
        security_epoch_provider=lambda: epoch[0], operations=Operations(), world=world,
    )
    again = restarted.reconcile(
        device_id=first['id'], session_id='s2', security_epoch=epoch[0], thread_id=thread, events=[body],
    )
    assert again['duplicate_client_event_ids'] == ['client-event-1']
    messages = continuity.events_for_thread(thread)
    assert [row['payload']['text'] for row in messages if row['kind'] == 'user_message'] == ['hello']


def test_replay_conflict_and_out_of_order_fail_closed(tmp_path):
    _, first, _, continuity, _, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Shared', device_id=first['id'])
    base = {'client_event_id': 'e1', 'client_sequence': 1, 'kind': 'user_message', 'payload': {'text': 'one'}}
    sync.reconcile(device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread, events=[base])
    with pytest.raises(ValueError, match='identity conflict'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread,
            events=[{**base, 'payload': {'text': 'changed'}}],
        )
    with pytest.raises(ValueError, match='sequence identity conflict|out-of-order|replayed'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread,
            events=[{'client_event_id': 'unknown-old', 'client_sequence': 1, 'kind': 'user_message', 'payload': {'text': 'old'}}],
        )


def test_out_of_order_batch_is_deterministically_sorted(tmp_path):
    _, first, _, continuity, _, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Shared', device_id=first['id'])
    result = sync.reconcile(
        device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread,
        events=[
            {'client_event_id': 'e2', 'client_sequence': 2, 'kind': 'user_message', 'payload': {'text': 'two'}},
            {'client_event_id': 'e1', 'client_sequence': 1, 'kind': 'user_message', 'payload': {'text': 'one'}},
        ],
    )
    assert result['accepted_client_event_ids'] == ['e1', 'e2']
    assert [row['payload']['text'] for row in continuity.events_for_thread(thread)] == ['one', 'two']


def test_security_epoch_invalidates_offline_sync_and_new_epoch_can_restart_sequence(tmp_path):
    _, first, _, continuity, _, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Shared', device_id=first['id'])
    sync.reconcile(
        device_id=first['id'], session_id='s1', security_epoch=7, thread_id=thread,
        events=[{'client_event_id': 'e1', 'client_sequence': 1, 'kind': 'user_message', 'payload': {'text': 'before'}}],
    )
    epoch[0] = 8
    with pytest.raises(PermissionError, match='stale security epoch'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=7, thread_id=thread,
            events=[{'client_event_id': 'e2', 'client_sequence': 2, 'kind': 'user_message', 'payload': {'text': 'stale'}}],
        )
    fresh = sync.reconcile(
        device_id=first['id'], session_id='s2', security_epoch=8, thread_id=thread,
        events=[{'client_event_id': 'e-new', 'client_sequence': 1, 'kind': 'user_message', 'payload': {'text': 'after'}}],
    )
    assert fresh['accepted_client_event_ids'] == ['e-new']


def test_forged_and_revoked_devices_fail_closed(tmp_path):
    registry, first, second, continuity, _, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Shared', device_id=first['id'])
    with pytest.raises(PermissionError, match='trusted active device'):
        sync.reconcile(device_id='forged-device', session_id='x', security_epoch=epoch[0], thread_id=thread, events=[])
    registry.revoke(second['id'])
    with pytest.raises(PermissionError, match='trusted active device'):
        sync.handoff(device_id=first['id'], session_id='s1', to_device=second['id'], thread_id=thread)


@pytest.mark.parametrize('key', [
    'password', 'passwd', 'secret', 'token', 'access_token', 'refresh_token',
    'api_key', 'authorization', 'cookie', 'credential', 'private_key',
    'raw_payload', 'content_bytes', 'audio_bytes', 'image_bytes',
])
def test_secret_and_raw_multimodal_sync_fields_fail_closed(tmp_path, key):
    _, first, _, continuity, _, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Shared', device_id=first['id'])
    with pytest.raises(ValueError, match='prohibited'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread,
            events=[{'client_event_id': f'e-{key}', 'client_sequence': 1, 'kind': 'user_message', 'payload': {'nested': {key: 'LEAK'}}}],
        )
    assert continuity.events_for_thread(thread) == []


def test_p7_projection_is_metadata_only_and_raw_payload_never_replicates(tmp_path):
    _, first, _, _, world, _, sync = fixture(tmp_path)
    observation = world.ingest(
        'document', {'text': 'RAW-CONTENT-MUST-NOT-REPLICATE'}, source='fixture', source_event_id='doc-1', device_id=first['id'],
    )
    projected = sync.observation_status(observation['id'], device_id=first['id'], session_id='s1')
    assert projected['observation_id'] == observation['id']
    assert 'payload' not in projected
    assert 'RAW-CONTENT-MUST-NOT-REPLICATE' not in str(projected)


def test_stale_p7_reference_cannot_be_bound_into_new_sync_event(tmp_path):
    _, first, _, continuity, world, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Shared', device_id=first['id'])
    observation = world.ingest(
        'screen', {'title': 'old'}, source='fixture', source_event_id='screen-1', device_id=first['id'],
        observed_at='2026-09-15T23:59:00+00:00', freshness_ttl_seconds=0,
    )
    with pytest.raises(PermissionError, match='stale|unavailable|restricted'):
        sync.reconcile(
            device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread,
            events=[{'client_event_id': 'ctx-1', 'client_sequence': 1, 'kind': 'context_ref',
                     'payload': {'source_refs': [f"observation:{observation['id']}"]}}],
        )


def test_p6_status_projection_hides_execution_authority(tmp_path):
    _, first, _, _, _, _, sync = fixture(tmp_path)
    projected = sync.operation_status('op-1', device_id=first['id'], session_id='s1')
    assert projected['status'] == 'waiting_approval'
    text = str(projected)
    for forbidden in ('MUST-NOT-LEAK', 'approval_id', 'session_id', 'parameters'):
        assert forbidden not in text


def test_workflow_scope_is_required_for_cross_device_p6_status(tmp_path):
    registry, first, _, _, _, _, sync = fixture(tmp_path)
    registry.set_permissions(first['id'], {'ai:chat'})
    with pytest.raises(PermissionError, match='workflow:read'):
        sync.operation_status('op-1', device_id=first['id'], session_id='s1')


def test_handoff_reuses_one_canonical_thread(tmp_path):
    _, first, second, continuity, _, _, sync = fixture(tmp_path)
    thread = continuity.create_thread('Shared', device_id=first['id'])
    continuity.append(thread, device_id=first['id'], kind='user_message', payload={'text': 'hello'})
    result = sync.handoff(device_id=first['id'], session_id='s1', to_device=second['id'], thread_id=thread)
    assert result['thread']['id'] == thread
    assert continuity.active_for_device(second['id'])['id'] == thread
    assert len(continuity.list_threads(include_closed=True)) == 1


def test_everywhere_surface_registry_refuses_revoked_device(tmp_path):
    registry, first, _, continuity, _, _, _ = fixture(tmp_path)
    everywhere = PersonalAIEverywhere(gate=Gate(True), device_registry=registry, continuity=continuity)
    assert everywhere.resume(first['id'], 'web')['resumed'] is True
    registry.revoke(first['id'])
    blocked = everywhere.resume(first['id'], 'web')
    assert blocked['resumed'] is False and blocked['blocked'] is True
    assert 'trusted' in blocked['reason']


def _api(tmp_path):
    registry, first, second, continuity, world, epoch, sync = fixture(tmp_path)
    sessions = PwaSessionStore(tmp_path / 'sessions.sqlite3')
    token, session = sessions.issue(first['id'])
    app = FastAPI()
    app.include_router(continuity_sync_router({'continuity_sync': sync}))
    app.add_middleware(PwaSessionMiddleware, sessions=sessions, device_registry=registry, cookie_max_age=3600)
    client = TestClient(app, base_url='https://testserver')
    cookies = {'pa_device': first['id'], 'pa_session': token}
    return client, cookies, registry, sessions, session, first, second, continuity, world, epoch, sync


def test_sync_api_requires_live_session_and_revocation_is_immediate(tmp_path):
    client, cookies, registry, sessions, session, first, _, _, _, _, _ = _api(tmp_path)
    assert client.get('/iphone/api/continuity/status').status_code == 401
    ok = client.get('/iphone/api/continuity/status', cookies=cookies)
    assert ok.status_code == 200 and ok.json()['device_id'] == first['id']
    sessions.revoke(session.id)
    assert client.get('/iphone/api/continuity/status', cookies=cookies).status_code == 401


def test_offline_device_reconnect_after_device_revocation_is_blocked(tmp_path):
    client, cookies, registry, _, _, first, _, _, _, _, _ = _api(tmp_path)
    assert client.get('/iphone/api/continuity/status', cookies=cookies).status_code == 200
    registry.revoke(first['id'])
    assert client.get('/iphone/api/continuity/status', cookies=cookies).status_code == 401


def test_sync_api_reconcile_and_handoff(tmp_path):
    client, cookies, _, _, _, first, second, continuity, _, epoch, _ = _api(tmp_path)
    thread = continuity.create_thread('API shared', device_id=first['id'])
    response = client.post(
        '/iphone/api/continuity/reconcile', cookies=cookies,
        json={'security_epoch': epoch[0], 'thread_id': thread, 'events': [
            {'client_event_id': 'api-1', 'client_sequence': 1, 'kind': 'user_message', 'payload': {'text': 'hello from web'}}
        ]},
    )
    assert response.status_code == 200
    handoff = client.post(
        '/iphone/api/continuity/handoff', cookies=cookies,
        json={'to_device': second['id'], 'thread_id': thread},
    )
    assert handoff.status_code == 200
    assert continuity.active_for_device(second['id'])['id'] == thread


def test_sqlite_integrity_and_duplicate_suppression_under_repeated_sync(tmp_path):
    _, first, _, continuity, _, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Shared', device_id=first['id'])
    for sequence in range(1, 31):
        event = {'client_event_id': f'e-{sequence}', 'client_sequence': sequence, 'kind': 'user_message', 'payload': {'text': f'message-{sequence}'}}
        sync.reconcile(device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread, events=[event])
        sync.reconcile(device_id=first['id'], session_id='s1', security_epoch=epoch[0], thread_id=thread, events=[event])
    with sync._con() as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert con.execute('SELECT COUNT(*) FROM continuity_sync_receipts').fetchone()[0] == 30
    assert len([e for e in continuity.events_for_thread(thread, limit=1000) if e['kind'] == 'user_message']) == 30


def test_stage8_live_permission_removal_blocks_established_continuity(tmp_path):
    registry, first, _, continuity, _, epoch, sync = fixture(tmp_path)
    thread=continuity.create_thread('live',device_id=first['id'])
    assert sync.status(device_id=first['id'],session_id='s1')['device_id']==first['id']
    registry.set_permissions(first['id'], {'workflow:read'})
    with pytest.raises(PermissionError,match='ai:chat'):
        sync.reconcile(device_id=first['id'],session_id='s1',security_epoch=epoch[0],thread_id=thread,events=[
            {'client_event_id':'revoked-1','client_sequence':1,'kind':'user_message','payload':{'text':'must not commit'}}
        ])
    assert [e for e in continuity.events_for_thread(thread) if e['kind']=='user_message']==[]


def test_stage8_handoff_target_revoked_at_precommit_boundary_fails_closed(tmp_path,monkeypatch):
    registry, first, second, continuity, _, _, sync = fixture(tmp_path)
    thread=continuity.create_thread('handoff-race',device_id=first['id'])
    original_set_active=continuity.set_active
    def revoke_before_commit(device_id, thread_id, *, authority_guard=None):
        if device_id==second['id']:
            registry.revoke(second['id'])
        return original_set_active(device_id,thread_id,authority_guard=authority_guard)
    monkeypatch.setattr(continuity,'set_active',revoke_before_commit)
    with pytest.raises(PermissionError,match='trusted active device'):
        sync.handoff(device_id=first['id'],session_id='s1',to_device=second['id'],thread_id=thread)

    # Inspect durable state before active_for_device(), whose fallback is
    # intentionally mutating and could otherwise manufacture the residue.
    with continuity.lock, continuity._con() as con:
        durable = con.execute(
            'SELECT active_thread_id FROM continuity_device_state WHERE device_id=?',
            (second['id'],),
        ).fetchone()
    assert durable is None or durable['active_thread_id'] is None
    with pytest.raises(PermissionError,match='trusted active device'):
        continuity.active_for_device(
            second['id'], authority_guard=lambda: sync._assert_device(second['id'])
        )
    with continuity.lock, continuity._con() as con:
        durable_after_lookup = con.execute(
            'SELECT active_thread_id FROM continuity_device_state WHERE device_id=?',
            (second['id'],),
        ).fetchone()
    assert durable_after_lookup is None or durable_after_lookup['active_thread_id'] is None
    assert [e for e in continuity.events_for_thread(thread) if e['kind']=='handoff']==[]

def test_stage8_handoff_source_revoked_at_precommit_boundary_fails_closed(tmp_path,monkeypatch):
    registry, first, second, continuity, _, _, sync = fixture(tmp_path)
    thread=continuity.create_thread('handoff-source-race',device_id=first['id'])

    with continuity.lock, continuity._con() as con:
        source_before = con.execute(
            'SELECT active_thread_id,last_event_id FROM continuity_device_state WHERE device_id=?',
            (first['id'],),
        ).fetchone()
        target_before = con.execute(
            'SELECT active_thread_id,last_event_id FROM continuity_device_state WHERE device_id=?',
            (second['id'],),
        ).fetchone()
    assert source_before is not None and source_before['active_thread_id'] == thread
    assert target_before is None or target_before['active_thread_id'] is None

    original_set_active=continuity.set_active
    def revoke_source_before_commit(device_id, thread_id, *, authority_guard=None):
        if device_id==second['id']:
            registry.revoke(first['id'])
        return original_set_active(device_id,thread_id,authority_guard=authority_guard)
    monkeypatch.setattr(continuity,'set_active',revoke_source_before_commit)

    with pytest.raises(PermissionError,match='trusted active device'):
        sync.handoff(device_id=first['id'],session_id='s1',to_device=second['id'],thread_id=thread)

    with continuity.lock, continuity._con() as con:
        source_after = con.execute(
            'SELECT active_thread_id,last_event_id FROM continuity_device_state WHERE device_id=?',
            (first['id'],),
        ).fetchone()
        target_after = con.execute(
            'SELECT active_thread_id,last_event_id FROM continuity_device_state WHERE device_id=?',
            (second['id'],),
        ).fetchone()
    assert dict(source_after) == dict(source_before)
    assert target_after is None or target_after['active_thread_id'] is None
    assert [e for e in continuity.events_for_thread(thread) if e['kind']=='handoff']==[]

    # Revocation changes authorization, not the pre-existing persistence record.
    with pytest.raises(PermissionError,match='trusted active device'):
        continuity.active_for_device(
            first['id'], authority_guard=lambda: sync._assert_device(first['id'])
        )
    with pytest.raises(PermissionError,match='trusted active device'):
        sync.status(device_id=first['id'],session_id='s1')

    # A governed target lookup must not create continuity residue after rejection.
    with pytest.raises(PermissionError,match='trusted active device'):
        continuity.active_for_device(
            first['id'], authority_guard=lambda: sync._assert_device(first['id'])
        )
    with continuity.lock, continuity._con() as con:
        target_final = con.execute(
            'SELECT active_thread_id,last_event_id FROM continuity_device_state WHERE device_id=?',
            (second['id'],),
        ).fetchone()
    assert target_final is None or target_final['active_thread_id'] is None

