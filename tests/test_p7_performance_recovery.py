from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import time

import pytest

from future_intelligence.multimodal import SimulatedObservationAdapter, WorldUnderstanding
from recovery.backup import BACKUP_MAGIC, BackupService


# P7 qualification measurements are emitted by the dedicated reliability performance step.
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


class Gate:
    def decision(self, phase):
        assert phase == 'p7'
        return type('Decision', (), {'allowed': True, 'reason': 'ok'})()


class Events:
    def __init__(self):
        self.items = []

    def emit(self, event, **payload):
        self.items.append({'event': event, **payload})


class FixedKeyStore:
    def get_or_create(self):
        return b'P' * 32


def _world(path, *, clock=None, events=None, audit=None):
    return WorldUnderstanding(
        gate=Gate(),
        path=path,
        clock=clock or (lambda: NOW),
        events=events,
        audit=audit,
    )


def test_p7_encrypted_backup_restore_preserves_governed_observation_state(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()
    source_db = source / 'future-intelligence' / 'world.sqlite3'
    source_db.parent.mkdir(parents=True)
    current = [NOW]

    w = _world(source_db, clock=lambda: current[0])
    screen = SimulatedObservationAdapter('screen-fixture', 'screen')
    active = screen.ingest(w, {'title': 'Home'}, source_event_id='active-event')
    w.record_capability('physical-offline', 'camera', 'offline', device_id='device-offline')

    raw = w.ingest(
        'document', {'name': 'source'}, source='owner-upload', source_event_id='raw-source',
        retention_policy='long', privacy_classification='internal',
    )
    child = w.ingest(
        'document', {'facts': ['one']}, source='extractor', source_event_id='derived-source',
        lineage_stage='derived', parent_observation_ids=[raw['id']], derivation_type='extract',
        retention_policy='long', privacy_classification='internal',
    )

    deleted = w.ingest('image', {'fixture': 'delete-me'}, source='fixture', source_event_id='delete-source')
    deleted_child = w.ingest(
        'image', {'facts': ['x']}, source='extractor', source_event_id='delete-child',
        lineage_stage='derived', parent_observation_ids=[deleted['id']], derivation_type='extract',
    )
    assert w.delete(deleted['id']) is True
    assert w.get(deleted_child['id']) is None

    expiring_raw = w.ingest(
        'screen', {'fixture': 'expiring-source'}, source='fixture', source_event_id='expire-raw',
        retention_policy='ephemeral',
    )
    expiring_child = w.ingest(
        'screen', {'fixture': 'long-child'}, source='fixture', source_event_id='expire-child',
        lineage_stage='derived', parent_observation_ids=[expiring_raw['id']], derivation_type='derive',
        retention_policy='long',
    )
    current[0] += timedelta(days=2)
    assert w.expire_due() == 2
    assert w.get(expiring_raw['id']) is None
    assert w.get(expiring_child['id']) is None

    backup = BackupService(source, root_key_store=FixedKeyStore())
    archive = backup.create('p7-state.paibackup')
    assert archive.read_bytes().startswith(BACKUP_MAGIC)
    manifest = backup.inspect(archive)
    assert manifest['encrypted'] is True
    assert any(row['path'] == 'future-intelligence/world.sqlite3' for row in manifest['files'])

    result = BackupService(target, root_key_store=FixedKeyStore()).restore(archive)
    assert result['ok'] is True
    assert result['encrypted'] is True

    restored_db = target / 'future-intelligence' / 'world.sqlite3'
    with sqlite3.connect(restored_db) as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'

    restored = _world(restored_db, clock=lambda: current[0])
    assert restored.storage_status()['loaded_observations_in_memory'] == 0
    assert restored.get(active['id'])['source_event_id'] == 'active-event'
    assert restored.get(raw['id'], allowed_classifications={'internal'})['retention_policy'] == 'long'
    assert restored.get(child['id'], allowed_classifications={'internal'})['parent_observation_ids'] == [raw['id']]
    assert [row['observation_id'] for row in restored.lineage(child['id'], allowed_classifications={'internal'})] == [child['id'], raw['id']]
    assert restored.capability('physical-offline')['state'] == 'offline'
    assert restored.get(deleted['id']) is None
    assert restored.get(deleted_child['id']) is None
    assert restored._get_unfiltered(deleted_child['id'])['retention_state'] == 'deleted'
    assert restored.get(expiring_raw['id']) is None
    assert restored.get(expiring_child['id']) is None
    assert restored._get_unfiltered(expiring_raw['id'])['retention_state'] == 'expired'
    assert restored._get_unfiltered(expiring_child['id'])['retention_state'] == 'expired'
    assert restored.lineage(expiring_child['id']) == []
    assert restored.expire_due() == 0

    duplicate = SimulatedObservationAdapter('screen-fixture', 'screen').ingest(
        restored, {'title': 'Home'}, source_event_id='active-event'
    )
    assert duplicate['id'] == active['id']
    assert duplicate['duplicate'] is True


def test_p7_indexed_queries_and_startup_are_bounded(tmp_path):
    db = tmp_path / 'world.sqlite3'
    w = _world(db)
    for index in range(1200):
        modality = 'screen' if index % 2 == 0 else 'document'
        w.ingest(
            modality,
            {'index': index},
            source=f'source-{index % 5}',
            source_event_id=f'event-{index}',
            device_id=None,
        )

    status = w.storage_status()
    assert status['observation_count'] == 1200
    assert status['loaded_observations_in_memory'] == 0
    assert status['database_bytes'] > 0

    restarted = _world(db)
    assert restarted.storage_status()['loaded_observations_in_memory'] == 0
    assert len(restarted.recent(limit=11)) == 11
    assert len(restarted.recent(limit=13, modality='screen')) == 13
    assert len(restarted.recent(limit=17, source='source-2')) == 17
    first = restarted.recent(limit=1)[0]
    assert restarted.get(first['id'])['id'] == first['id']

    with sqlite3.connect(db) as con:
        index_names = {row[1] for row in con.execute('PRAGMA index_list(observations)').fetchall()}
        assert 'idx_observations_time' in index_names
        assert 'idx_observations_modality_time' in index_names
        assert 'idx_observations_source_time' in index_names
        assert 'idx_observations_device_time' in index_names
        assert 'idx_observations_source_event' in index_names
        plan = ' '.join(
            str(cell)
            for row in con.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM observations WHERE modality='screen' ORDER BY observed_at DESC LIMIT 10"
            ).fetchall()
            for cell in row
        )
        assert 'idx_observations_modality_time' in plan
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_p7_performance_envelope_is_bounded_and_reported(tmp_path):
    measurements = []
    for label, volume in [('small', 100), ('medium', 600), ('large', 1800)]:
        db = tmp_path / f'{label}.sqlite3'
        started = time.perf_counter()
        w = _world(db)
        for index in range(volume):
            w.ingest(
                'document', {'index': index, 'bucket': index % 10},
                source=f'perf-{index % 10}', source_event_id=f'{label}-{index}',
            )
        ingest_seconds = time.perf_counter() - started

        restart_started = time.perf_counter()
        restarted = _world(db)
        restart_seconds = time.perf_counter() - restart_started

        query_started = time.perf_counter()
        rows = restarted.recent(limit=25, source='perf-3')
        query_seconds = time.perf_counter() - query_started

        duplicate_started = time.perf_counter()
        duplicate = restarted.ingest(
            'document', {'index': 3, 'bucket': 3}, source='perf-3', source_event_id=f'{label}-3'
        )
        duplicate_seconds = time.perf_counter() - duplicate_started

        status = restarted.storage_status()
        assert status['observation_count'] == volume
        assert status['loaded_observations_in_memory'] == 0
        assert 0 < len(rows) <= 25
        assert duplicate['duplicate'] is True
        measurements.append({
            'label': label,
            'observations': volume,
            'ingest_seconds': round(ingest_seconds, 6),
            'restart_seconds': round(restart_seconds, 6),
            'bounded_query_seconds': round(query_seconds, 6),
            'duplicate_seconds': round(duplicate_seconds, 6),
            'database_bytes': status['database_bytes'],
            'loaded_observations_in_memory': status['loaded_observations_in_memory'],
        })

    assert measurements[0]['database_bytes'] < measurements[-1]['database_bytes']
    assert all(row['loaded_observations_in_memory'] == 0 for row in measurements)
    print('P7_PERFORMANCE_RESULTS=' + json.dumps(measurements, sort_keys=True), flush=True)
    test_p7_extended_performance_paths_are_measured_and_bounded(tmp_path)


def test_sensor_rejection_classification_covers_nonfinite_malformed_unit_and_out_of_contract(tmp_path):
    events = Events()
    audit_rows = []
    w = _world(
        tmp_path / 'sensor-world.sqlite3',
        events=events,
        audit=lambda category, action, payload: audit_rows.append((category, action, payload)),
    )
    adapter = SimulatedObservationAdapter('sensor-fixture', 'device_sensor')
    invalid_payloads = [
        {'sensor_type': 'temperature', 'value': float('inf'), 'unit': 'c'},
        {'sensor_type': 'temperature', 'value': float('-inf'), 'unit': 'c'},
        {'sensor_type': 'temperature', 'value': float('nan'), 'unit': 'c'},
        {'sensor_type': 'temperature', 'value': 'not-a-number', 'unit': 'c'},
        {'sensor_type': 'temperature', 'value': 22.0, 'unit': 'x' * 41},
        {'sensor_type': 'temperature', 'value': {'unexpected': 1}, 'unit': 'c'},
    ]

    for index, payload in enumerate(invalid_payloads):
        rejected_before = sum(item.get('event') == 'world.observation.rejected' for item in events.items)
        with pytest.raises(ValueError):
            adapter.ingest(w, payload, source_event_id=f'invalid-sensor-{index}')
        rejected = [item for item in events.items if item.get('event') == 'world.observation.rejected']
        assert len(rejected) == rejected_before + 1
        assert rejected[-1] == {
            'event': 'world.observation.rejected',
            'reason': 'invalid_sensor_value',
            'modality': 'device_sensor',
        }
        assert audit_rows[-1][1] == 'observation.rejected'
        assert audit_rows[-1][2] == {
            'reason': 'invalid_sensor_value',
            'modality': 'device_sensor',
        }

    assert w.count(include_deleted=True) == 0
    serialized = json.dumps(events.items, sort_keys=True) + json.dumps(audit_rows, sort_keys=True)
    assert 'not-a-number' not in serialized
    assert 'unexpected' not in serialized


def test_secret_credentials_case_and_nested_list_fail_before_persistence_without_leakage(tmp_path, caplog):
    db = tmp_path / 'secret-world.sqlite3'
    events = Events()
    audit_rows = []
    w = _world(
        db,
        events=events,
        audit=lambda category, action, payload: audit_rows.append((category, action, payload)),
    )
    adapter = SimulatedObservationAdapter('document-fixture', 'document')
    marker = 'P7-DO-NOT-PERSIST-CREDENTIAL-VALUE'
    payloads = [
        {'credential': marker},
        {'nested': {'Credentials': marker}},
        {'nested': [{'CREDENTIAL': marker}]},
        {'nested': [{'access-token': marker}, {'api key': marker}]},
    ]

    for index, payload in enumerate(payloads):
        with pytest.raises(ValueError) as caught:
            adapter.ingest(w, payload, source_event_id=f'secret-{index}')
        assert marker not in str(caught.value)
        rejected = [item for item in events.items if item.get('event') == 'world.observation.rejected'][-1]
        assert rejected['reason'] == 'secret_bearing_payload'
        assert set(rejected) == {'event', 'reason', 'modality'}

    assert w.count(include_deleted=True) == 0
    assert w.recent(include_deleted=True) == []
    assert w.action_context()['observations'] == []
    assert marker not in caplog.text
    assert marker not in json.dumps(events.items, sort_keys=True)
    assert marker not in json.dumps(audit_rows, sort_keys=True)
    assert marker.encode() not in db.read_bytes()
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0


def test_multilevel_expiration_invalidates_all_descendants_and_survives_restart(tmp_path):
    current = [NOW]
    db = tmp_path / 'lineage-world.sqlite3'
    w = _world(db, clock=lambda: current[0])

    raw = w.ingest(
        'screen', {'stage': 'raw'}, source='fixture', source_event_id='raw', retention_policy='ephemeral'
    )
    extracted = w.ingest(
        'screen', {'stage': 'extracted'}, source='fixture', source_event_id='extracted',
        lineage_stage='extracted', parent_observation_ids=[raw['id']], derivation_type='extract',
        retention_policy='long',
    )
    interpreted = w.ingest(
        'screen', {'stage': 'interpreted'}, source='fixture', source_event_id='interpreted',
        lineage_stage='interpreted', parent_observation_ids=[extracted['id']], derivation_type='interpret',
        retention_policy='long',
    )
    derived = w.ingest(
        'screen', {'stage': 'derived'}, source='fixture', source_event_id='derived',
        lineage_stage='derived', parent_observation_ids=[interpreted['id']], derivation_type='derive',
        retention_policy='long',
    )
    sibling = w.ingest(
        'screen', {'stage': 'sibling'}, source='fixture', source_event_id='sibling',
        lineage_stage='derived', parent_observation_ids=[raw['id']], derivation_type='derive',
        retention_policy='long',
    )
    independent = w.ingest(
        'screen', {'stage': 'independent'}, source='fixture', source_event_id='independent', retention_policy='long'
    )
    multi_parent = w.ingest(
        'screen', {'stage': 'multi-parent'}, source='fixture', source_event_id='multi-parent',
        lineage_stage='derived', parent_observation_ids=[raw['id'], independent['id']],
        derivation_type='combine', retention_policy='long',
    )

    current[0] += timedelta(days=2)
    expired_count = w.expire_due()
    expired_ids = {raw['id'], extracted['id'], interpreted['id'], derived['id'], sibling['id'], multi_parent['id']}
    assert expired_count == len(expired_ids)
    for observation_id in expired_ids:
        assert w.get(observation_id) is None
        assert w.inspect(observation_id) is None
        assert w._get_unfiltered(observation_id)['retention_state'] == 'expired'
    assert w.get(independent['id']) is not None
    assert not expired_ids.intersection({row['id'] for row in w.recent(limit=50)})
    assert not expired_ids.intersection({row['observation_id'] for row in w.action_context()['observations']})

    restarted = _world(db, clock=lambda: current[0])
    assert restarted.expire_due() == 0
    for observation_id in expired_ids:
        assert restarted.get(observation_id) is None
        assert restarted.inspect(observation_id) is None
    assert restarted.lineage(derived['id']) == []
    assert restarted.get(independent['id']) is not None


def test_p7_extended_performance_paths_are_measured_and_bounded(tmp_path):
    db = tmp_path / 'extended-performance.sqlite3'
    w = _world(db)
    for index in range(300):
        w.ingest(
            'document', {'index': index}, source=f'perf-{index % 7}', source_event_id=f'base-{index}'
        )

    raw = w.ingest('image', {'stage': 'raw'}, source='perf-lineage', source_event_id='lineage-raw')
    extracted = w.ingest(
        'image', {'stage': 'extracted'}, source='perf-lineage', source_event_id='lineage-extracted',
        lineage_stage='extracted', parent_observation_ids=[raw['id']], derivation_type='extract',
    )
    interpreted = w.ingest(
        'image', {'stage': 'interpreted'}, source='perf-lineage', source_event_id='lineage-interpreted',
        lineage_stage='interpreted', parent_observation_ids=[extracted['id']], derivation_type='interpret',
    )
    derived = w.ingest(
        'image', {'stage': 'derived'}, source='perf-lineage', source_event_id='lineage-derived',
        lineage_stage='derived', parent_observation_ids=[interpreted['id']], derivation_type='derive',
    )

    started = time.perf_counter()
    lineage = w.lineage(derived['id'])
    provenance_lookup_seconds = time.perf_counter() - started
    assert [row['lineage_stage'] for row in lineage] == ['derived', 'interpreted', 'extracted', 'raw']

    def ingest_unique(index):
        return w.ingest(
            'screen', {'index': index}, source='concurrent-perf', source_event_id=f'concurrent-{index}'
        )

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        concurrent_rows = list(pool.map(ingest_unique, range(64)))
    concurrent_ingest_seconds = time.perf_counter() - started
    assert len({row['id'] for row in concurrent_rows}) == 64

    delete_parent = w.ingest('image', {'delete': True}, source='perf-delete', source_event_id='delete-parent')
    delete_child = w.ingest(
        'image', {'delete': 'child'}, source='perf-delete', source_event_id='delete-child',
        lineage_stage='derived', parent_observation_ids=[delete_parent['id']], derivation_type='derive',
    )
    started = time.perf_counter()
    assert w.delete(delete_parent['id']) is True
    delete_seconds = time.perf_counter() - started
    assert w.get(delete_child['id']) is None

    expiring_db = tmp_path / 'retention-performance.sqlite3'
    current = [NOW]
    expiring = _world(expiring_db, clock=lambda: current[0])
    for index in range(20):
        parent = expiring.ingest(
            'screen', {'index': index}, source='retention-perf', source_event_id=f'expire-parent-{index}',
            retention_policy='ephemeral',
        )
        expiring.ingest(
            'screen', {'index': index}, source='retention-perf', source_event_id=f'expire-child-{index}',
            lineage_stage='derived', parent_observation_ids=[parent['id']], derivation_type='derive',
            retention_policy='long',
        )
    current[0] += timedelta(days=2)
    started = time.perf_counter()
    expired = expiring.expire_due()
    retention_expire_seconds = time.perf_counter() - started
    assert expired == 40
    assert expiring.count() == 0

    restarted = _world(db)
    status = restarted.storage_status()
    assert status['loaded_observations_in_memory'] == 0
    assert status['observation_count'] >= 370
    result = {
        'provenance_lookup_seconds': round(provenance_lookup_seconds, 6),
        'concurrent_ingest_64_seconds': round(concurrent_ingest_seconds, 6),
        'delete_cascade_seconds': round(delete_seconds, 6),
        'retention_expire_40_seconds': round(retention_expire_seconds, 6),
        'database_bytes': status['database_bytes'],
        'loaded_observations_in_memory': status['loaded_observations_in_memory'],
    }
    print('P7_EXTENDED_PERFORMANCE_RESULTS=' + json.dumps(result, sort_keys=True), flush=True)
