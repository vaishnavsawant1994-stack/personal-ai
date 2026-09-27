from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from automation.engine import AutomationEngine
from capabilities.benchmark import CapabilityBenchmark
from core.events import EventBus
from devices.continuity import ContinuityService
from devices.gateway import DeviceGateway
from devices.registry import DeviceRegistry
from proactive.engine import AttentionRelevanceEngine
from server.api import create_app


class Executor:
    def chat(self, text, cancel_event=None):
        return f'reply:{text}'

    def approve(self, approval_id):
        return f'approved:{approval_id}'

    def reject(self, approval_id):
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
