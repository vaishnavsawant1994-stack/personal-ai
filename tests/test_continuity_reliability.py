from __future__ import annotations

import pytest

from devices.continuity import ContinuityService


def test_switching_to_older_thread_resets_device_cursor(tmp_path):
    service = ContinuityService(tmp_path / 'continuity.sqlite3')
    older = service.create_thread('Older', device_id='device-1')
    service.append(older, device_id='device-1', kind='user_message', payload={'text': 'old event'})
    assert service.sync('device-1')['events']

    newer = service.create_thread('Newer', device_id='device-1')
    service.append(newer, device_id='device-1', kind='user_message', payload={'text': 'new event'})
    assert service.sync('device-1')['events']

    service.set_active('device-1', older)
    switched = service.sync('device-1')
    assert switched['after_sequence'] == 0
    assert [event['payload']['text'] for event in switched['events']] == ['old event']


def test_conversation_reopens_after_service_restart_and_on_second_device(tmp_path):
    path = tmp_path / 'continuity.sqlite3'
    first = ContinuityService(path)
    thread = first.create_thread('Persistent conversation', device_id='browser-a')
    first.append(thread, device_id='browser-a', kind='user_message', payload={'text': 'question'})
    first.append(thread, device_id='browser-a', kind='assistant_message', payload={'text': 'answer'})

    restarted = ContinuityService(path)
    reopened = restarted.resume('browser-a', thread_id=thread, event_limit=20)
    second = restarted.resume('browser-b', thread_id=thread, event_limit=20)

    assert reopened['thread']['id'] == thread
    assert second['thread']['id'] == thread
    assert [event['kind'] for event in reopened['events']] == ['user_message', 'assistant_message']
    assert [event['payload']['text'] for event in second['events']] == ['question', 'answer']


def test_archive_removes_active_binding_but_preserves_export(tmp_path):
    service = ContinuityService(tmp_path / 'continuity.sqlite3')
    thread = service.create_thread('Archive me', device_id='device-1')
    service.append(thread, device_id='device-1', kind='user_message', payload={'text': 'keep'})

    assert service.archive_thread(thread) is True
    assert service.thread(thread)['closed_at'] is not None
    assert service.list_threads() == []
    assert service.list_threads(include_closed=True)[0]['id'] == thread
    exported = service.export_thread(thread)
    assert exported['conversation']['id'] == thread
    assert exported['events'][0]['payload']['text'] == 'keep'

    with pytest.raises(KeyError, match='archived'):
        service.resume('device-1', thread_id=thread)


def test_delete_removes_conversation_events_and_device_binding(tmp_path):
    service = ContinuityService(tmp_path / 'continuity.sqlite3')
    thread = service.create_thread('Delete me', device_id='device-1')
    service.append(thread, device_id='device-1', kind='user_message', payload={'text': 'remove'})

    assert service.delete_thread(thread) is True
    assert service.thread(thread) is None
    assert service.events_for_thread(thread) == []
    assert service.delete_thread(thread) is False

    resumed = service.resume('device-1')
    assert resumed['thread']['id'] != thread
