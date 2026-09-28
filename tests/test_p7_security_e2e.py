from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from devices.registry import DeviceRegistry
from future_intelligence.multimodal import ObservationAdapter, SimulatedObservationAdapter, WorldUnderstanding
from security.pwa_sessions import PwaSessionStore
from server.multimodal_world_api import multimodal_world_router
from server.pwa_session_middleware import PwaSessionMiddleware
from tests.p6_support import Harness


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


class Gate:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def decision(self, phase):
        assert phase == 'p7'
        return SimpleNamespace(allowed=self.allowed, reason='ok' if self.allowed else 'p3.permissions missing')


class Events:
    def __init__(self):
        self.items = []

    def emit(self, event, **payload):
        self.items.append({'event': event, **payload})


def world(tmp_path, *, clock=None, events=None, registry=None):
    return WorldUnderstanding(
        gate=Gate(),
        path=tmp_path / 'world.sqlite3',
        clock=clock or (lambda: NOW),
        events=events,
        device_registry=registry,
    )


def rejected(events):
    return [row for row in events.items if row['event'] == 'world.observation.rejected']


def test_rejected_adapter_audit_is_categorical_and_payload_free(tmp_path):
    events = Events()
    w = world(tmp_path, events=events)

    cases = []

    missing = ObservationAdapter('missing-capability', 'screen', capability_state='available')
    cases.append((missing, {'title': 'x'}, {'source_event_id': 'missing'}, 'adapter_unavailable'))

    denied = ObservationAdapter('denied', 'screen', capability_state='denied')
    denied.register(w)
    cases.append((denied, {'title': 'x'}, {'source_event_id': 'denied'}, 'permission_or_trust_denied'))

    simulated = SimulatedObservationAdapter('sim', 'document')
    simulated.register(w)
    cases.extend([
        (simulated, {'password': 'LEAK-PASSWORD'}, {'source_event_id': 'secret'}, 'secret_bearing_payload'),
        (simulated, {'url': 'https://secret.invalid/private?token=LEAK-URL'}, {'source_event_id': 'unsafe-ref'}, 'unsafe_content_reference'),
        (simulated, {'text': 'x'}, {'source_event_id': 'bad-time', 'observed_at': NOW + timedelta(hours=1)}, 'invalid_timestamp'),
        (simulated, {'text': 'x'}, {'source_event_id': 'bad-confidence', 'confidence': float('nan')}, 'invalid_confidence'),
    ])

    location = SimulatedObservationAdapter('loc', 'location')
    location.register(w)
    cases.append((location, {'latitude': 99.0, 'longitude': 8.0, 'note': 'LEAK-LOCATION'}, {'source_event_id': 'bad-loc'}, 'invalid_location'))

    sensor = SimulatedObservationAdapter('sensor', 'device_sensor')
    sensor.register(w)
    cases.append((sensor, {'sensor_type': 'temperature', 'value': float('inf'), 'unit': 'c'}, {'source_event_id': 'bad-sensor'}, 'invalid_sensor_value'))

    for adapter, payload, kwargs, expected_reason in cases:
        before = len(rejected(events))
        with pytest.raises((ValueError, PermissionError, RuntimeError)):
            adapter.ingest(w, payload, **kwargs)
        row = rejected(events)[before]
        assert row == {
            'event': 'world.observation.rejected',
            'reason': expected_reason,
            'modality': adapter.modality,
        }

    first = simulated.ingest(w, {'text': 'first'}, source_event_id='conflict')
    assert first['duplicate'] is False
    with pytest.raises(ValueError, match='identity conflict'):
        simulated.ingest(w, {'text': 'second'}, source_event_id='conflict')
    assert rejected(events)[-1]['reason'] == 'source_event_conflict'

    huge = {'items': list(range(WorldUnderstanding.MAX_COLLECTION_ITEMS + 1)), 'marker': 'LEAK-HUGE'}
    with pytest.raises(ValueError):
        simulated.ingest(w, huge, source_event_id='generic-invalid')
    assert rejected(events)[-1]['reason'] == 'invalid_observation_payload'

    audit_text = json.dumps(rejected(events), sort_keys=True)
    for forbidden in (
        'LEAK-PASSWORD', 'LEAK-URL', 'LEAK-LOCATION', 'LEAK-HUGE',
        'https://secret.invalid', 'token=', 'password', 'authorization', 'cookie',
    ):
        assert forbidden not in audit_text


def test_secret_key_variants_fail_closed_before_persistence(tmp_path):
    w = world(tmp_path)
    adapter = SimulatedObservationAdapter('secrets', 'document')
    adapter.register(w)
    keys = [
        'password', 'passwd', 'secret', 'token', 'access_token', 'refresh_token',
        'api_key', 'authorization', 'cookie', 'credential', 'private_key', 'db_password', 'client_secret',
    ]
    for index, key in enumerate(keys):
        payload = {'outer': {'nested': {key: f'value-{index}'}}}
        with pytest.raises(ValueError):
            adapter.ingest(w, payload, source_event_id=f'secret-{index}')
    assert w.count(include_deleted=True) == 0


def test_validation_adversarial_shapes_fail_closed(tmp_path):
    w = world(tmp_path)
    adapter = SimulatedObservationAdapter('validator', 'document')
    adapter.register(w)

    nested = {'leaf': 'x'}
    for _ in range(WorldUnderstanding.MAX_DEPTH + 2):
        nested = {'next': nested}
    attacks = [
        nested,
        {'text': 'x' * (WorldUnderstanding.MAX_STRING_CHARS + 1)},
        {'items': list(range(WorldUnderstanding.MAX_COLLECTION_ITEMS + 1))},
        {f'k{i}': i for i in range(WorldUnderstanding.MAX_METADATA_KEYS + 1)},
        {'path': '../../owner/private.txt'},
        {'uri': 'file:///etc/passwd'},
        {'url': 'http://127.0.0.1/admin'},
        {'number': float('inf')},
    ]
    for index, payload in enumerate(attacks):
        with pytest.raises(ValueError):
            adapter.ingest(w, payload, source_event_id=f'attack-{index}')
    assert w.count(include_deleted=True) == 0


def test_provenance_spoofing_missing_deleted_and_raw_parent_fail_closed(tmp_path):
    w = world(tmp_path)
    raw = w.ingest('image', {'fixture': 'raw'}, source='fixture', source_event_id='raw')

    with pytest.raises(ValueError, match='raw observations cannot claim parent'):
        w.ingest(
            'image', {'fixture': 'spoof'}, source='fixture', source_event_id='spoof',
            lineage_stage='raw', parent_observation_ids=[raw['id']],
        )
    with pytest.raises(ValueError, match='missing or inactive'):
        w.ingest(
            'image', {'fixture': 'missing'}, source='fixture', source_event_id='missing',
            lineage_stage='derived', parent_observation_ids=['does-not-exist'], derivation_type='spoof',
        )
    assert w.delete(raw['id']) is True
    with pytest.raises(ValueError, match='missing or inactive'):
        w.ingest(
            'image', {'fixture': 'deleted'}, source='fixture', source_event_id='deleted-parent',
            lineage_stage='derived', parent_observation_ids=[raw['id']], derivation_type='spoof',
        )


def _chain(w):
    raw = w.ingest('image', {'fixture': 'raw'}, source='fixture', source_event_id='raw')
    extracted = w.ingest(
        'image', {'facts': ['box']}, source='extractor', source_event_id='extracted',
        lineage_stage='extracted', parent_observation_ids=[raw['id']], derivation_type='object_extract',
    )
    interpreted = w.ingest(
        'image', {'meaning': 'package'}, source='interpreter', source_event_id='interpreted',
        lineage_stage='interpreted', parent_observation_ids=[extracted['id']], derivation_type='interpretation',
    )
    derived = w.ingest(
        'image', {'context': 'delivery'}, source='deriver', source_event_id='derived',
        lineage_stage='derived', parent_observation_ids=[interpreted['id']], derivation_type='context',
    )
    return raw, extracted, interpreted, derived


def test_multilevel_lineage_delete_cascades_and_survives_restart(tmp_path):
    w = world(tmp_path)
    rows = _chain(w)
    assert [row['lineage_stage'] for row in w.lineage(rows[-1]['id'])] == [
        'derived', 'interpreted', 'extracted', 'raw'
    ]
    assert w.delete(rows[0]['id']) is True
    assert w.delete(rows[0]['id']) is True
    for row in rows:
        assert w.get(row['id']) is None
        tombstone = w._get_unfiltered(row['id'])
        assert tombstone['payload'] == {}
        assert tombstone['provenance'] == {}
        assert tombstone['retention_state'] == 'deleted'
    restarted = world(tmp_path)
    assert restarted.lineage(rows[-1]['id']) == []
    assert restarted.action_context()['observations'] == []
    assert all(restarted.inspect(row['id']) is None for row in rows)


def test_concurrent_delete_and_read_never_returns_active_descendant_after_delete(tmp_path):
    w = world(tmp_path)
    rows = _chain(w)

    def reader(_):
        return w.get(rows[-1]['id'])

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(reader, i) for i in range(16)]
        assert w.delete(rows[0]['id']) is True
        [f.result() for f in futures]
    assert w.get(rows[-1]['id']) is None
    assert w.action_context()['observations'] == []


def test_expired_source_must_not_leave_active_derived_context(tmp_path):
    current = [NOW]
    w = world(tmp_path, clock=lambda: current[0])
    raw = w.ingest(
        'image', {'fixture': 'raw'}, source='fixture', source_event_id='expire-raw',
        retention_policy='ephemeral',
    )
    child = w.ingest(
        'image', {'facts': ['x']}, source='extractor', source_event_id='expire-child',
        lineage_stage='derived', parent_observation_ids=[raw['id']], derivation_type='extract',
        retention_policy='long',
    )
    current[0] += timedelta(days=2)
    assert w.expire_due() >= 1
    assert w.get(raw['id']) is None
    assert w.get(child['id']) is None
    assert w.action_context()['observations'] == []


def _owner_app(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, device_token = registry.enroll('owner browser', 'ios-pwa')
    sessions = PwaSessionStore(tmp_path / 'sessions.sqlite3')
    session_token, session = sessions.issue(device['id'])
    w = WorldUnderstanding(
        gate=Gate(), path=tmp_path / 'world.sqlite3', clock=lambda: NOW, device_registry=registry,
    )
    app = FastAPI()
    app.include_router(multimodal_world_router({'device_registry': registry, 'world_understanding': w}))
    app.add_middleware(
        PwaSessionMiddleware,
        sessions=sessions,
        device_registry=registry,
        cookie_max_age=3600,
    )
    client = TestClient(app, base_url='https://testserver')
    cookies = {'pa_device': device['id'], 'pa_token': device_token, 'pa_session': session_token}
    return client, cookies, registry, sessions, session, w


def test_owner_api_requires_live_session_device_and_safe_projection(tmp_path):
    client, cookies, registry, sessions, session, w = _owner_app(tmp_path)
    item = w.ingest('document', {'raw_text': 'NEVER-EXPOSE'}, source='upload', source_event_id='owner-1')

    assert client.get('/iphone/api/world/observations').status_code == 401
    bad = dict(cookies); bad['pa_token'] = 'wrong'
    assert client.get('/iphone/api/world/observations', cookies=bad).status_code == 401

    ok = client.get(f"/iphone/api/world/observations/{item['id']}", cookies=cookies)
    assert ok.status_code == 200
    text = ok.text
    assert 'NEVER-EXPOSE' not in text
    assert 'payload' not in ok.json()
    assert ok.json()['observation_id'] == item['id']

    sessions.revoke(session.id)
    assert client.get('/iphone/api/world/observations', cookies=cookies).status_code == 401


def test_owner_api_rejects_revoked_device_and_hides_restricted_deleted_state(tmp_path):
    client, cookies, registry, sessions, session, w = _owner_app(tmp_path)
    public = w.ingest('document', {'name': 'visible'}, source='upload', source_event_id='public')
    secret = w.ingest(
        'document', {'name': 'hidden'}, source='upload', source_event_id='secret',
        privacy_classification='secret',
    )
    assert client.get(f"/iphone/api/world/observations/{secret['id']}", cookies=cookies).status_code == 404
    assert client.delete(f"/iphone/api/world/observations/{public['id']}", cookies=cookies).status_code == 200
    assert client.get(f"/iphone/api/world/observations/{public['id']}", cookies=cookies).status_code == 404
    registry.revoke(cookies['pa_device'])
    assert client.get('/iphone/api/world/capabilities', cookies=cookies).status_code == 401


def test_p3_capability_states_and_untrusted_physical_source_fail_closed(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    w = world(tmp_path, registry=registry)

    unknown = ObservationAdapter('physical-unknown', 'screen', device_id='not-enrolled', capability_state='available')
    unknown.register(w)
    with pytest.raises(PermissionError, match='not active/trusted'):
        unknown.ingest(w, {'title': 'x'}, source_event_id='unknown')

    for state in ('permission_required', 'denied', 'unavailable', 'offline', 'unsupported'):
        adapter = ObservationAdapter(f'a-{state}', 'screen', capability_state=state)
        adapter.register(w)
        with pytest.raises(PermissionError, match=state):
            adapter.ingest(w, {'title': 'x'}, source_event_id=state)

    simulated = SimulatedObservationAdapter('simulation', 'screen')
    item = simulated.ingest(w, {'title': 'fixture'}, source_event_id='simulation')
    assert item['simulation'] is True
    assert item['device_trust_state'] == 'simulation'
    assert w.capability('simulation')['state'] == 'simulation_only'


def test_p7_context_cannot_manufacture_p6_approval_or_execution(tmp_path):
    root = tmp_path / 'p6'
    h = Harness(root, mode='ask')
    try:
        side = h.side_tool('consequential')
        w = WorldUnderstanding(gate=Gate(), path=tmp_path / 'world.sqlite3', clock=lambda: NOW)
        observed = w.ingest('screen', {'title': 'Owner screen'}, source='fixture', source_event_id='ctx')
        context = w.action_context()
        assert context['allowed_for_governed_action'] is True
        assert context['authorization_granted'] is False
        plan = h.operations.create_plan('Use evidence but preserve authority', [{
            'requested_tool': 'consequential',
            'parameters': {'reference': f"observation:{observed['id']}"},
        }])
        operation = h.operations.execute(plan['id'], **h.authority())['operation']
        assert operation['status'] == 'waiting_approval'
        assert side.value == 0
    finally:
        h.close()


def test_p7_context_does_not_bypass_emergency_stop(tmp_path):
    h = Harness(tmp_path / 'p6', mode='act')
    try:
        side = h.side_tool('consequential')
        w = WorldUnderstanding(gate=Gate(), path=tmp_path / 'world.sqlite3', clock=lambda: NOW)
        w.ingest('screen', {'title': 'Owner screen'}, source='fixture', source_event_id='ctx')
        assert w.action_context()['authorization_granted'] is False
        plan = h.operations.create_plan('Must remain stopped', [{
            'requested_tool': 'consequential', 'parameters': {'reference': 'observation:fixture'}
        }])
        h.tools.set_emergency_stop(True)
        result = h.operations.execute(plan['id'], **h.authority())
        assert result['blocked'] is True
        assert side.value == 0
        assert h.tools.emergency_stop is True
    finally:
        h.close()


def test_duplicate_delivery_restart_and_concurrent_unique_events_e2e(tmp_path):
    path = tmp_path / 'world.sqlite3'
    w = WorldUnderstanding(gate=Gate(), path=path, clock=lambda: NOW)
    adapter = SimulatedObservationAdapter('screen-fixture', 'screen')
    first = adapter.ingest(w, {'title': 'Home'}, source_event_id='same-event')
    duplicate = adapter.ingest(w, {'title': 'Home'}, source_event_id='same-event')
    assert duplicate['id'] == first['id']

    restarted = WorldUnderstanding(gate=Gate(), path=path, clock=lambda: NOW)
    adapter2 = SimulatedObservationAdapter('screen-fixture', 'screen')
    after_restart = adapter2.ingest(restarted, {'title': 'Home'}, source_event_id='same-event')
    assert after_restart['id'] == first['id']

    def add(index):
        return adapter2.ingest(restarted, {'title': f'Window {index}'}, source_event_id=f'unique-{index}')

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(add, range(40)))
    assert len({row['id'] for row in rows}) == 40
    with sqlite3.connect(path) as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert restarted.storage_status()['loaded_observations_in_memory'] == 0
