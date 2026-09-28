from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from automation.engine import AutomationEngine
from capabilities.benchmark import CapabilityBenchmark
from core.events import EventBus
from devices.continuity import ContinuityService
from devices.gateway import DeviceGateway
from devices.registry import DeviceRegistry
from proactive.engine import AttentionRelevanceEngine
from server.api import create_app


class Executor:
    def __init__(self):
        self.chat_calls = []

    def chat(self, text, cancel_event=None, **kwargs):
        self.chat_calls.append((text, dict(kwargs)))
        return f'reply:{text}'

    def approve(self, approval_id, **kwargs):
        return f'approved:{approval_id}'

    def reject(self, approval_id, **kwargs):
        return 'Action cancelled.'


class StubTools:
    settings = SimpleNamespace(autonomy_mode='ask')
    permissions = object()

    def get(self, name):
        raise KeyError(name)


def build_client(tmp_path):
    events = EventBus()
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    gateway = DeviceGateway(registry, events)
    executor = Executor()
    continuity = ContinuityService(tmp_path / 'continuity.sqlite3', events=events)
    proactive = AttentionRelevanceEngine(
        tmp_path / 'proactive.sqlite3',
        events=events,
        interruptions_per_hour=2,
    )
    automations = AutomationEngine(
        tmp_path / 'automations.sqlite3',
        executor=executor,
        events=events,
        default_retries=0,
    )
    runtime = {
        'events': events,
        'executor': executor,
        'continuity': continuity,
        'proactive': proactive,
        'automations': automations,
        'device_registry': registry,
        'device_gateway': gateway,
        'tools': StubTools(),
        'second_brain': SimpleNamespace(graph=lambda: {'nodes': [], 'edges': []}),
        'integrations': SimpleNamespace(list=lambda: []),
        'voice': None,
        'vault': object(),
        'backups': object(),
        'telemetry': object(),
        'memory': object(),
    }
    benchmark = CapabilityBenchmark(tmp_path / 'benchmark.sqlite3', runtime=runtime)
    runtime['benchmark'] = benchmark
    settings = SimpleNamespace(
        pairing_ttl_seconds=300,
        cloud_runtime_enabled=False,
    )
    app = create_app(
        executor,
        settings,
        device_registry=registry,
        device_gateway=gateway,
        second_brain=runtime['second_brain'],
        automations=automations,
        runtime=runtime,
    )
    return TestClient(app), runtime, registry


def auth_headers(device, token):
    return {'Authorization': f'Bearer {token}', 'X-Device-ID': device['id']}


def test_p2_api_rejects_untrusted_continuity_access(tmp_path):
    client, _, _ = build_client(tmp_path)
    response = client.post('/continuity/resume', json={})
    assert response.status_code == 401


def test_p2_api_continuity_resume_handoff_and_sync(tmp_path):
    client, runtime, registry = build_client(tmp_path)
    phone, phone_token = registry.enroll('Phone', 'ios')
    desktop, desktop_token = registry.enroll('Desktop', 'windows')

    resumed = client.post('/continuity/resume', json={}, headers=auth_headers(phone, phone_token))
    assert resumed.status_code == 200
    thread_id = resumed.json()['thread']['id']

    appended = client.post(
        '/continuity/append',
        json={'thread_id': thread_id, 'kind': 'user_message', 'payload': {'text': 'Research batteries'}},
        headers=auth_headers(phone, phone_token),
    )
    assert appended.status_code == 200

    handoff = client.post(
        '/continuity/handoff',
        json={'thread_id': thread_id, 'to_device': desktop['id']},
        headers=auth_headers(phone, phone_token),
    )
    assert handoff.status_code == 200
    assert handoff.json()['thread']['id'] == thread_id

    sync = client.get('/continuity/sync', headers=auth_headers(desktop, desktop_token))
    assert sync.status_code == 200
    assert sync.json()['thread']['id'] == thread_id
    assert runtime['continuity'].active_for_device(desktop['id'])['id'] == thread_id


def test_p2_api_workflow_proactive_and_benchmark_require_device_identity(tmp_path):
    client, _, registry = build_client(tmp_path)
    device, token = registry.enroll('Phone', 'android')
    registry.set_permissions(device['id'], registry.OWNER_SCOPES)
    headers = auth_headers(device, token)

    workflow = client.post(
        '/workflows/create',
        json={
            'title': 'Daily check',
            'trigger': {'type': 'manual'},
            'steps': [{'kind': 'prompt', 'prompt': 'check today', 'retries': 0, 'timeout_seconds': 5}],
        },
        headers=headers,
    )
    assert workflow.status_code == 200
    workflow_id = workflow.json()['workflow_id']

    listing = client.get('/workflows', headers=headers)
    assert listing.status_code == 200
    assert any(row['id'] == workflow_id for row in listing.json())

    proactive = client.post(
        '/proactive/consider',
        json={
            'source': 'calendar',
            'payload': {
                'id': 'meeting-1',
                'kind': 'meeting',
                'due_in_minutes': 10,
                'urgency': 0.9,
                'importance': 0.8,
                'message': 'Meeting soon',
            },
        },
        headers=headers,
    )
    assert proactive.status_code == 200
    assert proactive.json()['action'] in {'suggest', 'notify'}

    benchmark = client.post('/benchmark/run', json={'capability': 'cross_device'}, headers=headers)
    assert benchmark.status_code == 200
    assert benchmark.json()['capability'] == 'cross_device'
    assert benchmark.json()['label'] in {'Prototype', 'Functional'}

    assert client.get('/benchmark').status_code == 401


def test_stage7_continuity_sync_accepts_reconnect_cursor_without_advancing_truth():
    from pathlib import Path
    continuity = Path('devices/continuity.py').read_text(encoding='utf-8')
    api = Path('server/api.py').read_text(encoding='utf-8')
    assert 'after_sequence: int | None = None' in continuity
    assert 'requested_after = stored_after if after_sequence is None else max(0, int(after_sequence))' in continuity
    assert 'after = min(requested_after, stored_after)' in continuity
    assert 'after_sequence: int | None = None' in api
    assert 'after_sequence=after_sequence' in api


def test_stage8_revoked_websocket_cannot_mutate_continuity(tmp_path):
    client, runtime, registry = build_client(tmp_path)
    device, token = registry.enroll('Phone', 'ios')
    resumed = runtime['continuity'].resume(device['id'])
    thread_id = resumed['thread']['id']
    before = runtime['continuity'].events_for_thread(thread_id, limit=50)

    with client.websocket_connect(
        f"/device/ws/{device['id']}",
        headers={'Authorization': f'Bearer {token}'},
    ) as websocket:
        assert registry.revoke(device['id'])
        websocket.send_json({
            'type': 'continuity_event',
            'kind': 'user_message',
            'payload': {'text': 'must-not-survive-revocation'},
        })
        try:
            websocket.receive_json()
            assert False, 'revoked websocket should be closed before processing the message'
        except WebSocketDisconnect as exc:
            assert exc.code == 4401

    after = runtime['continuity'].events_for_thread(thread_id, limit=50)
    assert after == before
    assert device['id'] not in runtime['device_gateway'].online()


def test_stage8_legacy_api_rejects_nested_and_oversized_payloads(tmp_path):
    client, runtime, registry = build_client(tmp_path)
    device, token = registry.enroll('Phone', 'android')
    headers = auth_headers(device, token)
    thread = runtime['continuity'].resume(device['id'])['thread']['id']

    nested = {}
    cursor = nested
    for index in range(12):
        cursor['next'] = {}
        cursor = cursor['next']
    response = client.post(
        '/continuity/append',
        json={'thread_id': thread, 'kind': 'context_ref', 'payload': nested},
        headers=headers,
    )
    assert response.status_code == 413

    oversized = client.post(
        '/continuity/context',
        json={'thread_id': thread, 'patch': {'text': 'x' * 13000}},
        headers=headers,
    )
    assert oversized.status_code == 413

    too_many_steps = client.post(
        '/workflows/create',
        json={
            'title': 'bounded',
            'trigger': {'type': 'manual'},
            'steps': [{'kind': 'prompt', 'prompt': 'x'} for _ in range(51)],
        },
        headers=headers,
    )
    assert too_many_steps.status_code == 422


def test_stage8_legacy_control_routes_enforce_current_device_scopes(tmp_path):
    client, _, registry = build_client(tmp_path)
    device, token = registry.enroll('Limited device', 'android')
    headers = auth_headers(device, token)

    registry.set_permissions(device['id'], {'ai:chat', 'workflow:read'})
    denied = client.post(
        '/workflows/create',
        json={'title': 'blocked', 'trigger': {'type': 'manual'}, 'steps': [{'kind': 'prompt', 'prompt': 'x'}]},
        headers=headers,
    )
    assert denied.status_code == 403
    assert client.get('/workflows', headers=headers).status_code == 200

    registry.set_permissions(device['id'], {'workflow:write'})
    assert client.get('/workflows', headers=headers).status_code == 403


def test_stage8_dashboard_cannot_directly_dispatch_tools_or_consequential_device_actions(tmp_path):
    client, _, registry = build_client(tmp_path)
    owner, token = registry.enroll('Owner device', 'ios-pwa')
    registry.set_permissions(owner['id'], registry.OWNER_SCOPES)
    headers = auth_headers(owner, token)

    direct_tool = client.post('/dashboard/tool', json={'tool': 'anything', 'parameters': {}}, headers=headers)
    assert direct_tool.status_code == 409

    side_effect = client.post(
        f"/dashboard/device/{owner['id']}/command",
        json={'action': 'open_url', 'parameters': {'url': 'https://example.com'}, 'timeout': 1},
        headers=headers,
    )
    assert side_effect.status_code == 409


def test_stage8_live_websocket_loses_authority_when_ai_chat_scope_is_revoked(tmp_path):
    client, runtime, registry = build_client(tmp_path)
    device, token = registry.enroll('Phone', 'ios')
    thread_id = runtime['continuity'].resume(device['id'])['thread']['id']
    before = runtime['continuity'].events_for_thread(thread_id, limit=50)

    with client.websocket_connect(
        f"/device/ws/{device['id']}",
        headers={'Authorization': f'Bearer {token}'},
    ) as websocket:
        registry.set_permissions(device['id'], {'workflow:read'})
        websocket.send_json({
            'type': 'continuity_event',
            'kind': 'user_message',
            'payload': {'text': 'must-not-survive-scope-revocation'},
        })
        try:
            websocket.receive_json()
            assert False, 'scope-revoked websocket should be closed before processing the message'
        except WebSocketDisconnect as exc:
            assert exc.code == 4403

    assert runtime['continuity'].events_for_thread(thread_id, limit=50) == before
    assert device['id'] not in runtime['device_gateway'].online()


def test_stage8_continuity_handoff_rejects_target_without_ai_chat_scope(tmp_path):
    client, runtime, registry = build_client(tmp_path)
    source, source_token = registry.enroll('Source', 'ios')
    target, _ = registry.enroll('Target', 'windows')
    registry.set_permissions(target['id'], {'device:read'})
    # Snapshot the target binding without calling active_for_device(), because that
    # compatibility helper intentionally binds an unbound device to the latest thread.
    with runtime['continuity']._con() as con:
        target_before = con.execute(
            'SELECT active_thread_id FROM continuity_device_state WHERE device_id=?',
            (target['id'],),
        ).fetchone()
    thread_id = runtime['continuity'].resume(source['id'])['thread']['id']

    response = client.post(
        '/continuity/handoff',
        json={'thread_id': thread_id, 'to_device': target['id']},
        headers=auth_headers(source, source_token),
    )
    assert response.status_code == 403
    with runtime['continuity']._con() as con:
        target_after = con.execute(
            'SELECT active_thread_id FROM continuity_device_state WHERE device_id=?',
            (target['id'],),
        ).fetchone()
    assert target_after == target_before


def test_stage8_legacy_command_requires_and_forwards_stable_request_identity(tmp_path):
    client, runtime, registry = build_client(tmp_path)
    device, token = registry.enroll('Command device', 'android')
    headers = auth_headers(device, token)

    missing = client.post('/command', json={'text': 'do it'}, headers=headers)
    assert missing.status_code == 422

    request_id = 'request-identity-0001'
    response = client.post(
        '/command',
        json={'text': 'do it', 'request_id': request_id},
        headers=headers,
    )
    assert response.status_code == 200
    assert runtime['executor'].chat_calls[-1][1]['request_id'] == request_id
    assert runtime['executor'].chat_calls[-1][1]['device_id'] == device['id']


def test_stage8_manual_workflow_retry_reuses_one_durable_run(tmp_path):
    client, runtime, registry = build_client(tmp_path)
    device, token = registry.enroll('Workflow device', 'android')
    registry.set_permissions(device['id'], registry.OWNER_SCOPES)
    headers = auth_headers(device, token)
    created = client.post(
        '/workflows/create',
        json={
            'title': 'Idempotent manual run',
            'trigger': {'type': 'manual'},
            'steps': [{'kind': 'set', 'key': 'value', 'value': 1}],
        },
        headers=headers,
    )
    assert created.status_code == 200
    workflow_id = created.json()['workflow_id']

    missing = client.post('/workflows/run', json={'workflow_id': workflow_id}, headers=headers)
    assert missing.status_code == 422

    body = {'workflow_id': workflow_id, 'idempotency_key': 'manual-run-request-0001'}
    first = client.post('/workflows/run', json=body, headers=headers)
    second = client.post('/workflows/run', json=body, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()['run_id'] == first.json()['run_id']
    runs = [row for row in runtime['automations'].runs(workflow_id, 20) if row['idempotency_key'] == body['idempotency_key']]
    assert len(runs) == 1


def test_stage8_legacy_workflow_run_listing_respects_persisted_device_binding(tmp_path):
    client, runtime, registry = build_client(tmp_path)
    first, first_token = registry.enroll('First workflow device', 'android')
    second, second_token = registry.enroll('Second workflow device', 'android')
    registry.set_permissions(first['id'], {'workflow:read', 'workflow:write'})
    registry.set_permissions(second['id'], {'workflow:read'})

    workflow_id = runtime['automations'].create_workflow(
        'Device-bound legacy run',
        {'type': 'manual'},
        [{'kind': 'set', 'key': 'x', 'value': 'y'}],
    )
    created = client.post(
        '/workflows/run',
        json={'workflow_id': workflow_id, 'idempotency_key': 'stage8-device-bound-run'},
        headers=auth_headers(first, first_token),
    )
    assert created.status_code == 200
    run_id = created.json()['run_id']

    own = client.get(
        '/workflows/runs',
        params={'workflow_id': workflow_id},
        headers=auth_headers(first, first_token),
    )
    assert own.status_code == 200
    assert run_id in {row['id'] for row in own.json()}

    foreign = client.get(
        '/workflows/runs',
        params={'workflow_id': workflow_id},
        headers=auth_headers(second, second_token),
    )
    assert foreign.status_code == 200
    assert run_id not in {row['id'] for row in foreign.json()}
