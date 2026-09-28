from pathlib import Path


def test_runtime_transport_rejects_stale_snapshots_and_has_pending_timeout():
    source = Path('pwa/v1-runtime.js').read_text(encoding='utf-8')
    assert "api('/runtime-state')" in source
    assert 'sequence<=canonicalSequence' in source
    assert 'MAX_PENDING_AGE_MS' in source


def test_activities_projection_contract_is_the_ui_safe_shape():
    from activities.projection import ActivitiesProjection
    projected = ActivitiesProjection.project_entry({
        'id': 'a1', 'category': 'tool', 'action': 'completed', 'created_at': 'now',
        'payload': {'authorization': 'secret', 'nested': {'cookie': 'secret', 'safe': 'ok'}},
    })
    assert set(projected) == {'id', 'activity_id', 'kind', 'label', 'action', 'status', 'created_at', 'details'}
    assert projected['activity_id'] == 'a1'
    assert projected['details']['authorization'] == '[redacted]'
    assert projected['details']['nested']['cookie'] == '[redacted]'
    assert projected['details']['nested']['safe'] == 'ok'
