from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from future_intelligence.multimodal import ObservationAdapter, SimulatedObservationAdapter, WorldUnderstanding


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


class Gate:
    def __init__(self, allowed=False):
        self.allowed = allowed

    def decision(self, phase):
        assert phase == 'p7'
        return type('Decision', (), {'allowed': self.allowed, 'reason': 'ok' if self.allowed else 'p3.permissions missing'})()


class Events:
    def __init__(self):
        self.items = []

    def emit(self, event, **payload):
        self.items.append({'event': event, **payload})


class Registry:
    def __init__(self, active=()):
        self.active = set(active)
        self.allowed = set(active)

    def is_active(self, device_id):
        return device_id in self.active

    def authorize(self, device_id, scope):
        return device_id in self.allowed and scope == 'ai:chat'


def world(tmp_path, *, allowed=False, clock=None, events=None, registry=None, audit=None):
    return WorldUnderstanding(
        gate=Gate(allowed),
        path=tmp_path / 'world.sqlite3',
        clock=clock or (lambda: NOW),
        events=events,
        device_registry=registry,
        audit=audit,
    )


@pytest.mark.parametrize('modality', sorted(WorldUnderstanding.MODALITIES))
def test_simulated_adapter_supports_all_canonical_modalities_truthfully(tmp_path, modality):
    w = world(tmp_path)
    adapter = SimulatedObservationAdapter(f'fixture-{modality}', modality)
    payload = {'fixture': modality}
    if modality == 'location':
        payload = {'latitude': 50.1, 'longitude': 8.6}
    elif modality in {'device_sensor', 'wearable'}:
        payload = {'sensor_type': 'fixture', 'value': 1.0, 'unit': 'count'}
    item = adapter.ingest(w, payload, source_event_id=f'{modality}-1')
    assert item['simulation'] is True
    assert item['device_trust_state'] == 'simulation'
    assert w.capability(adapter.adapter_id)['state'] == 'simulation_only'


def test_capability_states_are_exact_and_denied_or_offline_cannot_ingest(tmp_path):
    w = world(tmp_path)
    for state in WorldUnderstanding.CAPABILITY_STATES - {'simulation_only'}:
        cap = w.record_capability(f'a-{state}', 'screen', state)
        assert cap['state'] == state
    denied = ObservationAdapter('denied', 'screen', capability_state='denied')
    denied.register(w)
    with pytest.raises(PermissionError, match='denied'):
        denied.ingest(w, {'title': 'x'}, source_event_id='e1')
    offline = ObservationAdapter('offline', 'screen', capability_state='offline')
    offline.register(w)
    with pytest.raises(PermissionError, match='offline'):
        offline.ingest(w, {'title': 'x'}, source_event_id='e2')


def test_validation_rejects_confidence_secrets_unsafe_refs_and_bad_unicode(tmp_path):
    w = world(tmp_path)
    for value in (-0.01, 1.01, float('nan'), float('inf')):
        with pytest.raises(ValueError, match='confidence'):
            w.ingest('screen', {}, source='test', confidence=value)
    with pytest.raises(ValueError, match='secret-bearing'):
        w.ingest('document', {'nested': {'api_key': 'do-not-store'}}, source='test')
    with pytest.raises(ValueError, match='unsafe content reference'):
        w.ingest('document', {'file_path': '../../etc/passwd'}, source='test')
    with pytest.raises(ValueError, match='unsafe content reference'):
        w.ingest('image', {'url': 'https://untrusted.invalid/a.png'}, source='test')
    with pytest.raises(ValueError, match='invalid text'):
        w.ingest('document', {'text': '\ud800'}, source='test')


def test_validation_rejects_depth_size_coordinates_sensor_and_future_timestamp(tmp_path):
    w = world(tmp_path)
    nested = {'x': 1}
    for _ in range(WorldUnderstanding.MAX_DEPTH + 1):
        nested = {'x': nested}
    with pytest.raises(ValueError, match='nesting'):
        w.ingest('document', nested, source='test')
    with pytest.raises(ValueError, match='string is too large'):
        w.ingest('document', {'text': 'x' * (WorldUnderstanding.MAX_STRING_CHARS + 1)}, source='test')
    with pytest.raises(ValueError, match='out of range'):
        w.ingest('location', {'latitude': 91, 'longitude': 8}, source='test')
    with pytest.raises(ValueError, match='unit is required'):
        w.ingest('wearable', {'sensor_type': 'heart_rate', 'value': 80}, source='test')
    with pytest.raises(ValueError, match='future'):
        w.ingest('screen', {}, source='test', observed_at=NOW + timedelta(minutes=10))


def test_source_event_idempotency_survives_restart_and_conflicts_fail_closed(tmp_path):
    path = tmp_path / 'world.sqlite3'
    first = WorldUnderstanding(gate=Gate(), path=path, clock=lambda: NOW)
    one = first.ingest('screen', {'title': 'Home'}, source='screen-capture', source_event_id='evt-1')
    duplicate = first.ingest('screen', {'title': 'Home'}, source='screen-capture', source_event_id='evt-1')
    assert duplicate['id'] == one['id']
    assert duplicate['duplicate'] is True
    second = WorldUnderstanding(gate=Gate(), path=path, clock=lambda: NOW)
    after_restart = second.ingest('screen', {'title': 'Home'}, source='screen-capture', source_event_id='evt-1')
    assert after_restart['id'] == one['id']
    assert second.count() == 1
    with pytest.raises(ValueError, match='identity conflict'):
        second.ingest('screen', {'title': 'Different'}, source='screen-capture', source_event_id='evt-1')


def test_concurrent_duplicate_ingestion_creates_one_logical_observation(tmp_path):
    path = tmp_path / 'world.sqlite3'
    w = WorldUnderstanding(gate=Gate(), path=path, clock=lambda: NOW)

    def ingest(_):
        return w.ingest('audio', {'transcript': 'hello'}, source='audio-fixture', source_event_id='same')

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(ingest, range(24)))
    assert len({row['id'] for row in rows}) == 1
    assert w.count() == 1


def test_distinct_repeated_sensor_readings_remain_distinct(tmp_path):
    w = world(tmp_path)
    first = w.ingest('device_sensor', {'sensor_type': 'temperature', 'value': 20, 'unit': 'c'}, source='sensor', source_event_id='1')
    second = w.ingest('device_sensor', {'sensor_type': 'temperature', 'value': 20, 'unit': 'c'}, source='sensor', source_event_id='2')
    assert first['id'] != second['id']
    assert w.count() == 2


def test_provenance_chain_preserves_raw_extracted_interpreted_boundary(tmp_path):
    w = world(tmp_path)
    raw = w.ingest('image', {'fixture': 'receipt'}, source='upload', source_event_id='raw')
    extracted = w.ingest(
        'image', {'facts': ['total=10']}, source='vision', source_event_id='extract',
        lineage_stage='extracted', parent_observation_ids=[raw['id']], derivation_type='ocr',
    )
    interpreted = w.ingest(
        'image', {'meaning': 'purchase receipt'}, source='model', source_event_id='interpret',
        lineage_stage='interpreted', parent_observation_ids=[extracted['id']], derivation_type='model_interpretation',
    )
    lineage = w.lineage(interpreted['id'])
    assert [row['lineage_stage'] for row in lineage] == ['interpreted', 'extracted', 'raw']
    assert lineage[0]['derivation_type'] == 'model_interpretation'
    assert lineage[-1]['derivation_type'] is None


def test_derived_observation_cannot_downgrade_secret_parent(tmp_path):
    w = world(tmp_path)
    raw = w.ingest('document', {'name': 'private'}, source='owner', source_event_id='raw', privacy_classification='secret')
    with pytest.raises(ValueError, match='downgrade'):
        w.ingest(
            'document', {'summary': 'x'}, source='model', source_event_id='derived', privacy_classification='normal',
            lineage_stage='derived', parent_observation_ids=[raw['id']], derivation_type='summary',
        )


def test_privacy_filtering_happens_before_count_and_recent_no_side_channel(tmp_path):
    w = world(tmp_path)
    normal = w.ingest('screen', {'title': 'safe'}, source='screen', source_event_id='n')
    w.ingest('screen', {'title': 'hidden'}, source='screen', source_event_id='s', privacy_classification='secret')
    assert w.count() == 1
    assert [row['id'] for row in w.recent()] == [normal['id']]
    assert w.count(allowed_classifications={'secret'}) == 1
    assert len(w.recent(allowed_classifications={'secret'})) == 1


def test_fresh_stale_unknown_and_expired_are_truthful(tmp_path):
    current = [NOW]
    w = world(tmp_path, clock=lambda: current[0])
    fresh = w.ingest('screen', {'title': 'fresh'}, source='screen', source_event_id='1')
    document = w.ingest('document', {'name': 'static'}, source='upload', source_event_id='2')
    assert fresh['freshness'] == 'fresh'
    assert document['freshness'] == 'unknown'
    current[0] = NOW + timedelta(minutes=3)
    assert w.get(fresh['id'])['freshness'] == 'stale'
    expiring = w.ingest('audio', {'transcript': 'x'}, source='mic', source_event_id='3', retention_policy='ephemeral')
    current[0] = current[0] + timedelta(days=2)
    assert w.freshness_state(w._get_unfiltered(expiring['id'])) == 'expired'
    assert w.expire_due() >= 1
    assert w.get(expiring['id']) is None


def test_delete_cascades_to_derived_and_redacts_payload(tmp_path):
    w = world(tmp_path)
    raw = w.ingest('image', {'pixels': 'fixture'}, source='camera', source_event_id='1')
    derived = w.ingest(
        'image', {'objects': ['box']}, source='vision', source_event_id='2', lineage_stage='derived',
        parent_observation_ids=[raw['id']], derivation_type='object_detection',
    )
    assert w.delete(raw['id']) is True
    assert w.get(raw['id']) is None
    assert w.get(derived['id']) is None
    tombstone = w._get_unfiltered(derived['id'])
    assert tombstone['payload'] == {}
    assert tombstone['retention_state'] == 'deleted'


def test_p7_gate_and_trusted_device_are_required_for_governed_context(tmp_path):
    registry = Registry(active={'owner-device'})
    w = world(tmp_path, registry=registry)
    w.ingest('screen', {'title': 'Home'}, source='screen', source_event_id='1')
    blocked = w.action_context(requesting_device_id='owner-device')
    assert blocked['allowed_for_governed_action'] is False
    assert blocked['observations'] == []
    w.gate.allowed = True
    missing_device = w.action_context()
    assert missing_device['allowed_for_governed_action'] is False
    allowed = w.action_context(requesting_device_id='owner-device')
    assert allowed['allowed_for_governed_action'] is True
    assert allowed['authorization_granted'] is False
    assert allowed['source_refs'][0].startswith('observation:')


def test_stale_and_secret_observations_do_not_reach_default_governed_context(tmp_path):
    current = [NOW]
    w = world(tmp_path, allowed=True, clock=lambda: current[0])
    w.ingest('screen', {'title': 'old'}, source='screen', source_event_id='old')
    w.ingest('screen', {'title': 'secret'}, source='screen', source_event_id='secret', privacy_classification='secret')
    current[0] += timedelta(minutes=10)
    assert w.action_context()['observations'] == []


def test_persistent_storage_does_not_load_whole_ledger_into_ram(tmp_path):
    w = world(tmp_path)
    for index in range(500):
        w.ingest('document', {'index': index}, source='fixture', source_event_id=str(index))
    restarted = world(tmp_path)
    status = restarted.storage_status()
    assert status['observation_count'] == 500
    assert status['loaded_observations_in_memory'] == 0
    assert len(restarted.recent(limit=7)) == 7
    assert not hasattr(restarted, '_observations')


def test_events_and_audit_receive_safe_metadata_only(tmp_path):
    events = Events()
    audit_rows = []
    w = world(tmp_path, events=events, audit=lambda category, action, payload: audit_rows.append((category, action, payload)))
    item = w.ingest('screen', {'private_text': 'DO NOT LOG'}, source='screen', source_event_id='1')
    event_text = json.dumps(events.items)
    audit_text = json.dumps(audit_rows)
    assert 'DO NOT LOG' not in event_text
    assert 'DO NOT LOG' not in audit_text
    assert item['id'] in event_text
    assert item['id'] in audit_text


def test_legacy_schema_is_migrated_additively_without_startup_list(tmp_path):
    path = tmp_path / 'world.sqlite3'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE observations(id TEXT PRIMARY KEY,observed_at TEXT NOT NULL,document TEXT NOT NULL)')
        con.execute(
            'INSERT INTO observations VALUES(?,?,?)',
            ('legacy-id', NOW.isoformat(), json.dumps({'id': 'legacy-id', 'modality': 'document', 'payload': {'name': 'old'}, 'source': 'legacy-upload', 'confidence': 0.8, 'observed_at': NOW.isoformat()})),
        )
    w = WorldUnderstanding(gate=Gate(), path=path, clock=lambda: NOW)
    item = w.get('legacy-id')
    assert item['source_event_id'] == 'legacy:legacy-id'
    assert item['schema_version'] == WorldUnderstanding.SCHEMA_VERSION
    assert w.storage_status()['loaded_observations_in_memory'] == 0
