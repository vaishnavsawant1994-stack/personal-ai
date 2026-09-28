from __future__ import annotations

from activities.projection import ActivitiesProjection
from memory.store import MemoryStore


def test_activities_projection_recursively_redacts_secrets(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    store.audit('tool', 'execute', {
        'tool': 'example',
        'ok': True,
        'authorization': 'Bearer super-secret',
        'nested': {
            'api_key': 'secret-key',
            'cookie': 'session=secret',
            'safe': 'visible',
            'deeper': [{'refresh_token': 'nope', 'result_id': 'r-1'}],
        },
    })
    row = ActivitiesProjection(store).list(limit=1)[0]
    assert row['details']['authorization'] == '[redacted]'
    assert row['details']['nested']['api_key'] == '[redacted]'
    assert row['details']['nested']['cookie'] == '[redacted]'
    assert row['details']['nested']['deeper'][0]['refresh_token'] == '[redacted]'
    assert row['details']['nested']['safe'] == 'visible'
    assert row['details']['nested']['deeper'][0]['result_id'] == 'r-1'


def test_activities_projection_blocks_raw_private_context(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    store.audit('knowledge', 'retrieved', {
        'source_id': 'doc-1',
        'raw_knowledge': 'private document body',
        'raw_memory': 'private owner memory',
        'raw_camera': {'pixels': 'secret'},
        'system_prompt': 'hidden',
    })
    details = ActivitiesProjection(store).list(limit=1)[0]['details']
    assert details['source_id'] == 'doc-1'
    assert details['raw_knowledge'] == '[redacted]'
    assert details['raw_memory'] == '[redacted]'
    assert details['raw_camera'] == '[redacted]'
    assert details['system_prompt'] == '[redacted]'


def test_activities_projection_is_read_only_over_canonical_audit(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    audit_id = store.audit('approval', 'required', {'approval_id': 'a-1', 'tool': 'mail'})
    before = store.audit_entries(limit=10)
    projected = ActivitiesProjection(store).list(limit=10)
    after = store.audit_entries(limit=10)
    assert before == after
    assert projected[0]['id'] == audit_id
    assert projected[0]['status'] == 'needs_approval'


def test_activities_bounds_arbitrary_strings_and_lists():
    entry = {
        'id': 'x', 'category': 'tool', 'action': 'execute', 'created_at': 'now',
        'payload': {'text': 'x' * 5000, 'items': list(range(1000))},
    }
    projected = ActivitiesProjection.project_entry(entry)
    assert len(projected['details']['text']) == 1000
    assert len(projected['details']['items']) == 100
