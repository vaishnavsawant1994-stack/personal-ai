from __future__ import annotations

from types import SimpleNamespace

import pytest

from devices.continuity import ContinuityService
from devices.continuity_sync import ContinuitySync
from devices.registry import DeviceRegistry
from future_intelligence.multimodal import WorldUnderstanding


class Gate:
    def decision(self, phase):
        assert phase in {'p7', 'p8'}
        return SimpleNamespace(allowed=True, reason='ok')


class Operations:
    def operation(self, operation_id):
        if operation_id != 'op-cross-device':
            return None
        return {
            'operation_id': operation_id,
            'plan_id': 'plan-cross-device',
            'status': 'waiting_approval',
            'outcome_state': 'DISPATCHED',
            'current_step': 1,
            'risk_summary': {'highest_risk': 'external_side_effect'},
            'source_refs': [],
            'created_at': '2026-09-16T00:00:00+00:00',
            'updated_at': '2026-09-16T00:01:00+00:00',
            'completed_at': None,
            'approval_id': 'DO-NOT-EXPOSE',
        }


def fixture(tmp_path):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    web, _ = registry.enroll('web', 'web-pwa')
    mobile, _ = registry.enroll('mobile', 'ios-pwa')
    desktop, _ = registry.enroll('desktop', 'desktop')
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3')
    world = WorldUnderstanding(gate=Gate(), path=tmp_path / 'world.sqlite3', device_registry=registry)
    epoch = [4]
    sync = ContinuitySync(
        continuity,
        gate=Gate(),
        device_registry=registry,
        security_epoch_provider=lambda: epoch[0],
        operations=Operations(),
        world=world,
    )
    return registry, web, mobile, desktop, continuity, world, epoch, sync


def event(event_id, sequence, text):
    return {
        'client_event_id': event_id,
        'client_sequence': sequence,
        'kind': 'user_message',
        'payload': {'text': text},
    }


def test_web_to_mobile_to_desktop_continues_one_canonical_conversation(tmp_path):
    _, web, mobile, desktop, continuity, _, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('One conversation', device_id=web['id'])
    web_result = sync.reconcile(
        device_id=web['id'], session_id='web-session', security_epoch=epoch[0],
        thread_id=thread, events=[event('web-1', 1, 'from web')],
    )
    assert web_result['accepted_client_event_ids'] == ['web-1']

    first_handoff = sync.handoff(
        device_id=web['id'], session_id='web-session', to_device=mobile['id'], thread_id=thread,
    )
    assert first_handoff['thread']['id'] == thread
    mobile_view = sync.reconcile(
        device_id=mobile['id'], session_id='mobile-session', security_epoch=epoch[0],
        thread_id=thread, events=[event('mobile-1', 1, 'from mobile')], limit=20,
    )
    assert mobile_view['accepted_client_event_ids'] == ['mobile-1']

    second_handoff = sync.handoff(
        device_id=mobile['id'], session_id='mobile-session', to_device=desktop['id'], thread_id=thread,
    )
    assert second_handoff['thread']['id'] == thread
    desktop_view = sync.reconcile(
        device_id=desktop['id'], session_id='desktop-session', security_epoch=epoch[0],
        thread_id=thread, events=[], limit=20,
    )
    texts = [row['payload'].get('text') for row in desktop_view['server_events'] if row['kind'] == 'user_message']
    assert texts == ['from web', 'from mobile']
    assert len(continuity.list_threads(include_closed=True)) == 1


def test_authorized_offline_batch_reconciles_once_and_replay_is_idempotent(tmp_path):
    _, _, mobile, _, continuity, _, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Offline queue', device_id=mobile['id'])
    queued = [event('offline-1', 1, 'queued one'), event('offline-2', 2, 'queued two')]
    result = sync.reconcile(
        device_id=mobile['id'], session_id='reconnected-session', security_epoch=epoch[0],
        thread_id=thread, events=list(reversed(queued)), limit=10,
    )
    assert result['accepted_client_event_ids'] == ['offline-1', 'offline-2']
    replay = sync.reconcile(
        device_id=mobile['id'], session_id='reconnected-session', security_epoch=epoch[0],
        thread_id=thread, events=queued, limit=10,
    )
    assert replay['accepted_client_event_ids'] == []
    assert replay['duplicate_client_event_ids'] == ['offline-1', 'offline-2']
    assert len([row for row in continuity.events_for_thread(thread) if row['kind'] == 'user_message']) == 2


def test_revoked_offline_device_cannot_reconcile_after_reconnect(tmp_path):
    registry, _, mobile, _, continuity, _, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Revoked offline', device_id=mobile['id'])
    assert registry.revoke(mobile['id']) is True
    with pytest.raises(PermissionError, match='trusted active device'):
        sync.reconcile(
            device_id=mobile['id'], session_id='offline-session', security_epoch=epoch[0],
            thread_id=thread, events=[event('revoked-1', 1, 'must not land')],
        )
    assert continuity.events_for_thread(thread) == []


def test_cross_device_p6_status_and_p7_reference_remain_context_only(tmp_path):
    _, web, mobile, _, continuity, world, epoch, sync = fixture(tmp_path)
    thread = continuity.create_thread('Authority boundaries', device_id=web['id'])
    observation = world.ingest(
        'screen', {'title': 'Owner context'}, source='fixture', source_event_id='cross-device-context',
        device_id=web['id'], freshness_ttl_seconds=300,
    )
    handoff = sync.handoff(
        device_id=web['id'], session_id='web-session', to_device=mobile['id'], thread_id=thread,
    )
    assert handoff['thread']['id'] == thread

    projected_observation = sync.observation_status(
        observation['id'], device_id=mobile['id'], session_id='mobile-session',
    )
    assert projected_observation['observation_id'] == observation['id']
    assert 'payload' not in projected_observation

    operation = sync.operation_status(
        'op-cross-device', device_id=mobile['id'], session_id='mobile-session',
    )
    assert operation['status'] == 'waiting_approval'
    assert 'approval_id' not in operation
    assert 'DO-NOT-EXPOSE' not in str(operation)

    context = sync.reconcile(
        device_id=mobile['id'], session_id='mobile-session', security_epoch=epoch[0], thread_id=thread,
        events=[{
            'client_event_id': 'context-1', 'client_sequence': 1, 'kind': 'context_ref',
            'payload': {'source_refs': [f"observation:{observation['id']}", 'operation:op-cross-device']},
        }],
    )
    assert context['accepted_client_event_ids'] == ['context-1']
