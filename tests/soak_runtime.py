from __future__ import annotations

import argparse
import asyncio
import base64
import gc
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.conditions import evaluate_condition
from devices.continuity import ContinuityService
from devices.continuity_sync import ContinuitySync
from devices.gateway import DeviceCommand, DeviceGateway
from devices.registry import DeviceRegistry
from future_intelligence.multimodal import SimulatedObservationAdapter, WorldUnderstanding
from memory.store import MemoryStore
from security.vault import SecretVault
from voice.openai_realtime import OpenAIRealtimeVoiceSession


class Events:
    def emit(self, *args, **kwargs):
        pass


class Registry:
    def is_active(self, device_id):
        return True


class P7Gate:
    def decision(self, phase):
        assert phase == 'p7'
        return SimpleNamespace(allowed=True, reason='ok')


class P8Gate:
    def decision(self, phase):
        assert phase == 'p8'
        return SimpleNamespace(allowed=True, reason='ok')


def realtime_settings():
    return SimpleNamespace(
        openai_api_key='test',
        realtime_provider='openai',
        realtime_model='gpt-realtime-2.1',
        realtime_voice='marin',
        realtime_reasoning_effort='low',
        realtime_safety_identifier='',
        realtime_instructions='test',
        realtime_sample_rate=24000,
    )


async def verify_device_pending_cleanup(gateway, i):
    try:
        await gateway.request('offline', DeviceCommand('device_info', {}, f'soak-{i}'), timeout=.01)
    except RuntimeError:
        pass
    assert not gateway._pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=45)
    args = parser.parse_args()
    proc = psutil.Process(os.getpid())
    start = proc.memory_info().rss
    peak = start
    deadline = time.time() + args.seconds
    i = 0
    p7_events = 0
    p8_events = 0
    p8_sequence = 0

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        db = root / 'soak.sqlite3'
        world_db = root / 'world.sqlite3'
        continuity_db = root / 'continuity.sqlite3'
        store = MemoryStore(db)
        current_password = 'soak-password'
        vault = SecretVault(root / 'vault.json', current_password)
        events = Events()
        gateway = DeviceGateway(Registry(), events)
        realtime = OpenAIRealtimeVoiceSession(realtime_settings(), events)
        world = WorldUnderstanding(gate=P7Gate(), path=world_db, events=events)
        screen = SimulatedObservationAdapter('p7-soak-screen', 'screen')

        p8_registry = DeviceRegistry(root / 'p8-devices.sqlite3')
        p8_first, _ = p8_registry.enroll('p8-soak-web', 'web-pwa')
        p8_second, _ = p8_registry.enroll('p8-soak-mobile', 'ios-pwa')
        continuity = ContinuityService(continuity_db, events=events)
        thread = continuity.create_thread('P8 soak', device_id=p8_first['id'])
        continuity_sync = ContinuitySync(
            continuity,
            gate=P8Gate(),
            device_registry=p8_registry,
            security_epoch_provider=lambda: 11,
            events=events,
        )

        while time.time() < deadline:
            store.remember(
                type='note', subject=f's{i % 100}', content=f'c{i}', source='soak',
                confidence=.5, verified=False, tags=['soak'],
            )
            store.search('c', limit=10)
            assert evaluate_condition({'path': 'n', 'op': 'gte', 'value': 1}, {'n': 1})

            if i % 20 == 0:
                item = screen.ingest(world, {'title': f'soak-{i}'}, source_event_id=f'p7-screen-{i}')
                dup = screen.ingest(world, {'title': f'soak-{i}'}, source_event_id=f'p7-screen-{i}')
                assert dup['id'] == item['id'] and dup['duplicate'] is True
                assert len(world.recent(limit=5)) <= 5
                assert world.capability('p7-soak-screen')['state'] == 'simulation_only'
                p7_events += 1

            if i % 30 == 0:
                p8_sequence += 1
                event = {
                    'client_event_id': f'p8-soak-{p8_sequence}',
                    'client_sequence': p8_sequence,
                    'kind': 'user_message',
                    'payload': {'text': f'continuity-{p8_sequence}'},
                }
                accepted = continuity_sync.reconcile(
                    device_id=p8_first['id'], session_id='p8-soak-session', security_epoch=11,
                    thread_id=thread, events=[event], limit=5,
                )
                duplicate = continuity_sync.reconcile(
                    device_id=p8_first['id'], session_id='p8-soak-session', security_epoch=11,
                    thread_id=thread, events=[event], limit=5,
                )
                assert accepted['accepted_client_event_ids'] == [event['client_event_id']]
                assert duplicate['duplicate_client_event_ids'] == [event['client_event_id']]
                assert len(duplicate['server_events']) <= 5
                p8_events += 1

            if i % 100 == 0:
                raw = world.ingest('image', {'fixture': i}, source='p7-soak', source_event_id=f'p7-raw-{i}')
                child = world.ingest(
                    'image', {'fact': i}, source='p7-soak-derived', source_event_id=f'p7-child-{i}',
                    lineage_stage='derived', parent_observation_ids=[raw['id']], derivation_type='soak',
                )
                assert len(world.lineage(child['id'])) == 2
                assert world.delete(raw['id']) is True
                assert world.get(child['id']) is None
                try:
                    screen.ingest(world, {'api_key': 'must-never-persist'}, source_event_id=f'p7-reject-{i}')
                except ValueError:
                    pass
                else:
                    raise AssertionError('P7 secret-bearing soak payload was accepted')

            if i % 150 == 0:
                handoff = continuity_sync.handoff(
                    device_id=p8_first['id'], session_id='p8-soak-session',
                    to_device=p8_second['id'], thread_id=thread,
                )
                assert handoff['thread']['id'] == thread
                assert continuity.active_for_device(p8_second['id'])['id'] == thread

            if i % 200 == 0:
                try:
                    continuity_sync.reconcile(
                        device_id=p8_first['id'], session_id='p8-soak-session', security_epoch=11,
                        thread_id=thread,
                        events=[{
                            'client_event_id': f'p8-secret-{i}',
                            'client_sequence': p8_sequence + 1,
                            'kind': 'user_message',
                            'payload': {'api_key': 'must-never-sync'},
                        }],
                    )
                except ValueError:
                    pass
                else:
                    raise AssertionError('P8 secret-bearing sync payload was accepted')

            if i % 50 == 0:
                vault.set('rotation-probe', str(i))
                assert vault.get('rotation-probe') == str(i)
                encoded = base64.b64encode(f'audio-{i}'.encode()).decode()
                realtime.handle_event({'type': 'response.output_audio.delta', 'delta': encoded})
                assert realtime._play_q.get_nowait() == f'audio-{i}'.encode()

            if i % 250 == 0:
                asyncio.run(verify_device_pending_cleanup(gateway, i))

            if i % 500 == 0:
                current_password = f'soak-password-{i}'
                vault.rotate_password(current_password)
                assert vault.get('rotation-probe') == str(i)
                continuity_sync = ContinuitySync(
                    ContinuityService(continuity_db, events=events),
                    gate=P8Gate(), device_registry=p8_registry,
                    security_epoch_provider=lambda: 11, events=events,
                )
                gc.collect()
                peak = max(peak, proc.memory_info().rss)
            i += 1

        integrity = sqlite3.connect(db).execute('PRAGMA integrity_check').fetchone()[0]
        assert integrity == 'ok'
        p7_integrity = sqlite3.connect(world_db).execute('PRAGMA integrity_check').fetchone()[0]
        assert p7_integrity == 'ok'
        with sqlite3.connect(continuity_db) as con:
            p8_integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
            p8_receipts = con.execute('SELECT COUNT(*) FROM continuity_sync_receipts').fetchone()[0]
            p8_messages = con.execute("SELECT COUNT(*) FROM continuity_events WHERE kind='user_message'").fetchone()[0]
            page_count = con.execute('PRAGMA page_count').fetchone()[0]
            page_size = con.execute('PRAGMA page_size').fetchone()[0]
        assert p8_integrity == 'ok'
        assert p8_receipts == p8_events
        assert p8_messages == p8_events

        vault_reloaded = SecretVault(root / 'vault.json', current_password)
        assert vault_reloaded.get('rotation-probe') is not None
        restarted = WorldUnderstanding(gate=P7Gate(), path=world_db)
        p7_status = restarted.storage_status()
        assert p7_status['loaded_observations_in_memory'] == 0
        assert p7_status['observation_count'] >= p7_events

    end = proc.memory_info().rss
    growth = end - start
    if growth > 256 * 1024 * 1024:
        raise SystemExit(f'memory growth too high: {growth}')
    print({
        'iterations': i,
        'rss_start': start,
        'rss_peak': peak,
        'rss_end': end,
        'rss_growth': growth,
        'sqlite_integrity': integrity,
        'pending_device_requests': len(gateway._pending),
        'p7_events': p7_events,
        'p7_sqlite_integrity': p7_integrity,
        'p7_observations': p7_status['observation_count'],
        'p7_database_bytes': p7_status['database_bytes'],
        'p7_loaded_observations_in_memory': p7_status['loaded_observations_in_memory'],
        'p8_events': p8_events,
        'p8_sqlite_integrity': p8_integrity,
        'p8_receipts': p8_receipts,
        'p8_messages': p8_messages,
        'p8_database_bytes': int(page_count) * int(page_size),
    })


if __name__ == '__main__':
    main()
