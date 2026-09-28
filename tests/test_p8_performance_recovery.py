from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import time
from types import SimpleNamespace

from devices.continuity import ContinuityService
from devices.continuity_sync import ContinuitySync
from devices.registry import DeviceRegistry
from recovery.backup import BACKUP_MAGIC, BackupService


class Gate:
    def decision(self, phase):
        assert phase == 'p8'
        return SimpleNamespace(allowed=True, reason='ok')


class FixedKeyStore:
    def get_or_create(self):
        return b'8' * 32


def _sync(root, *, epoch=7):
    registry = DeviceRegistry(root / 'devices.sqlite3')
    continuity = ContinuityService(root / 'continuity.sqlite3')
    sync = ContinuitySync(
        continuity,
        gate=Gate(),
        device_registry=registry,
        security_epoch_provider=lambda: epoch,
    )
    return registry, continuity, sync


def _event(event_id: str, sequence: int, text: str):
    return {
        'client_event_id': event_id,
        'client_sequence': sequence,
        'kind': 'user_message',
        'payload': {'text': text},
    }


def test_concurrent_duplicate_delivery_is_one_logical_event(tmp_path):
    registry, continuity, sync = _sync(tmp_path)
    device, _ = registry.enroll('concurrent', 'web-pwa')
    thread = continuity.create_thread('Concurrent', device_id=device['id'])
    event = _event('same-event', 1, 'once')

    def deliver(_):
        return sync.reconcile(
            device_id=device['id'],
            session_id='session-1',
            security_epoch=7,
            thread_id=thread,
            events=[event],
            limit=5,
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(deliver, range(24)))

    accepted = sum('same-event' in row['accepted_client_event_ids'] for row in results)
    duplicates = sum('same-event' in row['duplicate_client_event_ids'] for row in results)
    assert accepted == 1
    assert duplicates == 23
    assert len([row for row in continuity.events_for_thread(thread) if row['kind'] == 'user_message']) == 1
    with sync._con() as con:
        assert con.execute('SELECT COUNT(*) FROM continuity_sync_receipts').fetchone()[0] == 1
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_p8_encrypted_backup_restore_preserves_sync_identity_and_revocation(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    registry, continuity, sync = _sync(source)
    first, _ = registry.enroll('first', 'web-pwa')
    second, _ = registry.enroll('second', 'ios-pwa')
    revoked, _ = registry.enroll('revoked', 'desktop')
    assert registry.revoke(revoked['id']) is True

    thread = continuity.create_thread('Restorable', device_id=first['id'])
    for sequence in range(1, 6):
        sync.reconcile(
            device_id=first['id'], session_id='source-session', security_epoch=7, thread_id=thread,
            events=[_event(f'event-{sequence}', sequence, f'message-{sequence}')], limit=2,
        )
    duplicate = sync.reconcile(
        device_id=first['id'], session_id='source-session', security_epoch=7, thread_id=thread,
        events=[_event('event-3', 3, 'message-3')], limit=2,
    )
    assert duplicate['duplicate_client_event_ids'] == ['event-3']
    sync.handoff(device_id=first['id'], session_id='source-session', to_device=second['id'], thread_id=thread)

    archive = BackupService(source, root_key_store=FixedKeyStore()).create('p8-state.paibackup')
    assert archive.read_bytes().startswith(BACKUP_MAGIC)
    manifest = BackupService(source, root_key_store=FixedKeyStore()).inspect(archive)
    assert manifest['encrypted'] is True
    paths = {row['path'] for row in manifest['files']}
    assert {'continuity.sqlite3', 'devices.sqlite3'}.issubset(paths)

    restored = BackupService(target, root_key_store=FixedKeyStore()).restore(archive)
    assert restored['ok'] is True and restored['encrypted'] is True
    assert 'devices.sqlite3' in restored['skipped_security_state']
    assert not (target / 'devices.sqlite3').exists()
    with sqlite3.connect(target / 'continuity.sqlite3') as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert con.execute('SELECT COUNT(*) FROM continuity_sync_receipts').fetchone()[0] == 5

    # Durable continuity and replay evidence are recoverable, but device trust is
    # intentionally not. A disaster restore must require fresh device enrollment.
    restored_registry, restored_continuity, restored_sync = _sync(target)
    assert restored_registry.is_active(first['id']) is False
    assert restored_registry.is_active(second['id']) is False
    assert restored_registry.is_active(revoked['id']) is False
    assert restored_continuity.active_for_device(second['id'])['id'] == thread
    messages = [row for row in restored_continuity.events_for_thread(thread) if row['kind'] == 'user_message']
    assert [row['payload']['text'] for row in messages] == [f'message-{i}' for i in range(1, 6)]

    try:
        restored_sync.reconcile(
            device_id=first['id'], session_id='restored-session', security_epoch=7, thread_id=thread,
            events=[_event('event-3', 3, 'message-3')], limit=2,
        )
        assert False, 'archived device trust must not survive restore'
    except PermissionError:
        pass


def test_p8_indexed_storage_and_bounded_retrieval(tmp_path):
    registry, continuity, sync = _sync(tmp_path)
    device, _ = registry.enroll('bounded', 'web-pwa')
    thread = continuity.create_thread('Bounded', device_id=device['id'])
    for start in range(1, 1001, 100):
        events = [_event(f'e-{seq}', seq, f'message-{seq}') for seq in range(start, min(start + 100, 1001))]
        sync.reconcile(
            device_id=device['id'], session_id='bounded-session', security_epoch=7,
            thread_id=thread, events=events, limit=1,
        )

    restarted = ContinuitySync(
        ContinuityService(tmp_path / 'continuity.sqlite3'),
        gate=Gate(), device_registry=registry, security_epoch_provider=lambda: 7,
    )
    page = restarted.reconcile(
        device_id=device['id'], session_id='bounded-session-2', security_epoch=7,
        thread_id=thread, events=[], after_sequence=995, limit=3,
    )
    assert len(page['server_events']) == 3
    assert [row['sequence'] for row in page['server_events']] == [996, 997, 998]

    with sqlite3.connect(tmp_path / 'continuity.sqlite3') as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        indexes = {row[1] for row in con.execute('PRAGMA index_list(continuity_sync_receipts)').fetchall()}
        assert 'idx_continuity_sync_receipts_thread' in indexes
        event_indexes = {row[1] for row in con.execute('PRAGMA index_list(continuity_events)').fetchall()}
        assert 'idx_continuity_events_thread' in event_indexes
        plan = ' '.join(
            str(cell)
            for row in con.execute(
                'EXPLAIN QUERY PLAN SELECT * FROM continuity_events WHERE thread_id=? AND id>? ORDER BY id ASC LIMIT 3',
                (thread, 995),
            ).fetchall()
            for cell in row
        )
        assert 'idx_continuity_events_thread' in plan
        assert con.execute('SELECT COUNT(*) FROM continuity_sync_receipts').fetchone()[0] == 1000


def test_p8_performance_envelope_is_bounded_and_reported(tmp_path):
    measurements = []
    for label, volume in [('small', 100), ('medium', 500), ('large', 1200)]:
        root = tmp_path / label
        registry, continuity, sync = _sync(root)
        device, _ = registry.enroll(label, 'web-pwa')
        thread = continuity.create_thread(label, device_id=device['id'])

        started = time.perf_counter()
        for batch_start in range(1, volume + 1, 100):
            stop = min(batch_start + 100, volume + 1)
            events = [_event(f'{label}-{seq}', seq, f'message-{seq}') for seq in range(batch_start, stop)]
            sync.reconcile(
                device_id=device['id'], session_id='perf-session', security_epoch=7,
                thread_id=thread, events=events, limit=1,
            )
        ingest_seconds = time.perf_counter() - started

        restart_started = time.perf_counter()
        restarted = ContinuitySync(
            ContinuityService(root / 'continuity.sqlite3'),
            gate=Gate(), device_registry=registry, security_epoch_provider=lambda: 7,
        )
        restart_seconds = time.perf_counter() - restart_started

        query_started = time.perf_counter()
        page = restarted.reconcile(
            device_id=device['id'], session_id='perf-session-2', security_epoch=7,
            thread_id=thread, events=[], after_sequence=max(0, volume - 25), limit=25,
        )
        query_seconds = time.perf_counter() - query_started

        duplicate_started = time.perf_counter()
        duplicate = restarted.reconcile(
            device_id=device['id'], session_id='perf-session-2', security_epoch=7,
            thread_id=thread, events=[_event(f'{label}-{volume}', volume, f'message-{volume}')], limit=1,
        )
        duplicate_seconds = time.perf_counter() - duplicate_started

        with sqlite3.connect(root / 'continuity.sqlite3') as con:
            receipts = con.execute('SELECT COUNT(*) FROM continuity_sync_receipts').fetchone()[0]
            integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
            page_count = con.execute('PRAGMA page_count').fetchone()[0]
            page_size = con.execute('PRAGMA page_size').fetchone()[0]
        assert receipts == volume
        assert integrity == 'ok'
        assert 0 < len(page['server_events']) <= 25
        assert duplicate['duplicate_client_event_ids'] == [f'{label}-{volume}']
        measurements.append({
            'label': label,
            'events': volume,
            'ingest_seconds': round(ingest_seconds, 6),
            'restart_seconds': round(restart_seconds, 6),
            'bounded_query_seconds': round(query_seconds, 6),
            'duplicate_seconds': round(duplicate_seconds, 6),
            'database_bytes': int(page_count) * int(page_size),
        })

    assert measurements[0]['database_bytes'] < measurements[-1]['database_bytes']
    print('P8_PERFORMANCE_RESULTS=' + json.dumps(measurements, sort_keys=True), flush=True)
