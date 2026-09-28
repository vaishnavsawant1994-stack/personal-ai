from types import SimpleNamespace
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from automation.engine import AutomationEngine
from devices.registry import DeviceRegistry
from knowledge.store import KnowledgeStore
from memory.second_brain import SecondBrain
from memory.store import MemoryStore
from qualification.program import P3QualificationProgram
from server.owner_product import owner_product_router
from security.request_context import TrustedRequestContext, set_trusted_request, reset_trusted_request


class Executor:
    def __init__(self):
        self.cancelled = []

    def chat(self, prompt, cancel_event=None, **kwargs):
        return f'done:{prompt}'

    def cancel_active_turns(self, *, reason='emergency_stop'):
        self.cancelled.append(reason)
        return 1


class Models:
    def status(self):
        return {'state': 'configured', 'primary_provider': 'test'}


class Tools:
    emergency_stop = False

    def all(self):
        return []

    def set_emergency_stop(self, enabled):
        self.emergency_stop = bool(enabled)
        return self.emergency_stop


class SessionStoreProbe:
    def __init__(self):
        self.revoked_devices = []

    def revoke_device(self, device_id):
        self.revoked_devices.append(device_id)
        return 1


class GatewayProbe:
    def __init__(self):
        self.disconnected = []

    def disconnect(self, device_id):
        self.disconnected.append(device_id)


def make_client(tmp_path, *, reauthenticated_at=None):
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, token = registry.enroll('Owner iPhone', 'ios-pwa')
    registry.set_permissions(device['id'], registry.OWNER_SCOPES)
    memory = MemoryStore(tmp_path / 'memory.sqlite3')
    executor = Executor()
    automations = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=executor)
    runtime = {
        'device_registry': registry,
        'memory': memory,
        'second_brain': SecondBrain(memory),
        'knowledge': KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects'),
        'automations': automations,
        'executor': executor,
        'pwa_sessions': SessionStoreProbe(),
        'cloud_sessions': SessionStoreProbe(),
        'device_gateway': GatewayProbe(),
        'p3_qualification': P3QualificationProgram(tmp_path / 'qualification.sqlite3'),
        'models': Models(),
        'tools': Tools(),
        'integrations': SimpleNamespace(list=lambda: []),
        'future_intelligence': SimpleNamespace(status=lambda: {}),
    }
    app = FastAPI()
    fresh_at = time.time() if reauthenticated_at is None else reauthenticated_at
    class TrustedContextMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            device_id = request.cookies.get('pa_device') or device['id']
            token = set_trusted_request(TrustedRequestContext(device_id, 'test-session', fresh_at))
            try:
                return await call_next(request)
            finally:
                reset_trusted_request(token)
    app.add_middleware(TrustedContextMiddleware)
    app.include_router(owner_product_router(runtime))
    client = TestClient(app, base_url='https://testserver')
    client.cookies.set('pa_device', device['id'])
    client.cookies.set('pa_token', token)
    return client, runtime, device


def test_owner_memory_lifecycle_and_audit(tmp_path):
    client, runtime, _ = make_client(tmp_path)
    created = client.post('/iphone/api/memory', json={
        'type': 'project',
        'subject': 'Aurora',
        'content': 'Aurora is active',
        'sensitivity': 'normal',
    })
    assert created.status_code == 200
    memory_id = created.json()['id']
    assert client.get('/iphone/api/memory/graph').json()['nodes'][0]['id'] == memory_id
    assert client.get('/iphone/api/memory/tree').json()['roots'][0]['id'] == memory_id
    corrected = client.patch(f'/iphone/api/memory/{memory_id}', json={'content': 'Aurora is paused'})
    assert corrected.status_code == 200
    assert corrected.json()['content'] == 'Aurora is paused'
    assert client.get('/iphone/api/memory/export').json()['memories'][0]['id'] == memory_id
    assert client.delete(f'/iphone/api/memory/{memory_id}').status_code == 409
    assert client.delete(f'/iphone/api/memory/{memory_id}?confirm=true').status_code == 200
    actions = [row['action'] for row in runtime['memory'].audit_entries('owner-product')]
    assert 'memory.created' in actions
    assert 'memory.corrected' in actions
    assert 'memory.deleted' in actions


def test_owner_api_refuses_to_create_or_mark_durable_never_store_memory(tmp_path):
    client, runtime, _ = make_client(tmp_path)

    refused = client.post('/iphone/api/memory', json={
        'type': 'fact',
        'subject': 'Temporary secret',
        'content': 'Do not retain this',
        'sensitivity': 'never_store',
    })
    assert refused.status_code == 409
    assert runtime['memory'].graph()['nodes'] == []

    created = client.post('/iphone/api/memory', json={
        'type': 'fact', 'subject': 'Stored', 'content': 'Owner chose to retain this',
    })
    memory_id = created.json()['id']
    update = client.patch(
        f'/iphone/api/memory/{memory_id}', json={'sensitivity': 'never_store'}
    )
    assert update.status_code == 409
    assert runtime['memory'].get(memory_id)['sensitivity'] == 'normal'


def test_owner_knowledge_lifecycle_and_citations(tmp_path):
    client, _, _ = make_client(tmp_path)
    created = client.post('/iphone/api/knowledge', json={
        'filename': 'facts.txt',
        'text': 'The approved launch city is Berlin.',
        'source': 'owner:test-case',
    })
    assert created.status_code == 200
    document_id = created.json()['id']
    search = client.get('/iphone/api/knowledge/search?q=launch+city').json()['results'][0]
    assert search['citation']['document_id'] == document_id
    assert search['citation']['source'] == 'owner:test-case'
    assert client.patch(f'/iphone/api/knowledge/{document_id}', json={'title': 'Launch facts'}).json()['title'] == 'Launch facts'
    assert client.delete(f'/iphone/api/knowledge/{document_id}').status_code == 409
    assert client.delete(f'/iphone/api/knowledge/{document_id}?confirm=true').status_code == 200


def test_owner_can_manage_other_device_and_revocation_is_immediate(tmp_path):
    client, runtime, owner = make_client(tmp_path)
    other, other_token = runtime['device_registry'].enroll('Desktop browser', 'web')

    listed = client.get('/iphone/api/devices')
    assert listed.status_code == 200
    assert listed.json()['current_device_id'] == owner['id']
    assert {row['id'] for row in listed.json()['devices']} == {owner['id'], other['id']}

    scopes = client.patch(
        f"/iphone/api/devices/{other['id']}/permissions",
        json={'scopes': ['ai:chat', 'memory:read']},
    )
    assert scopes.status_code == 200
    assert scopes.json()['scopes'] == ['ai:chat', 'memory:read']
    revoked = client.post(f"/iphone/api/devices/{other['id']}/revoke", json={'confirm': True})
    assert revoked.status_code == 200
    assert runtime['device_registry'].authenticate(other['id'], other_token) is False
    assert runtime['pwa_sessions'].revoked_devices == [other['id']]
    assert runtime['cloud_sessions'].revoked_devices == [other['id']]
    assert runtime['device_gateway'].disconnected == [other['id']]
    assert revoked.json()['revoked_sessions'] == {'pwa_sessions': 1, 'cloud_sessions': 1}


def test_workflow_permission_revocation_cancels_device_bound_work(tmp_path):
    client, runtime, _ = make_client(tmp_path)
    other, _ = runtime['device_registry'].enroll('Workflow browser', 'web')
    runtime['device_registry'].set_permissions(other['id'], {'ai:chat', 'workflow:write'})

    cancelled = []
    runtime['automations'].cancel_device_runs = (
        lambda device_id, *, reason='device_revoked':
        cancelled.append((device_id, reason)) or 2
    )

    response = client.patch(
        f"/iphone/api/devices/{other['id']}/permissions",
        json={'scopes': ['ai:chat']},
    )

    assert response.status_code == 200
    assert response.json()['cancelled_turns'] == 0
    assert response.json()['cancelled_workflows'] == 2
    assert cancelled == [(other['id'], 'workflow_permission_revoked')]


def test_ui_preferences_are_scoped_to_the_trusted_device_and_persist(tmp_path):
    client, runtime, owner = make_client(tmp_path)

    defaults = client.get('/iphone/api/preferences')
    assert defaults.json() == {
        'continuous_voice': True,
        'voice_rate': 1.0,
        'quiet_hours': True,
    }
    updated = client.put('/iphone/api/preferences', json={
        'continuous_voice': False,
        'voice_rate': 1.15,
        'quiet_hours': False,
    })
    assert updated.status_code == 200
    assert client.get('/iphone/api/preferences').json() == updated.json()
    assert 'ui.preferences' in runtime['device_registry'].metadata(owner['id'])

    other, token = runtime['device_registry'].enroll('Other browser', 'web')
    other_client = TestClient(client.app, base_url='https://testserver')
    other_client.cookies.set('pa_device', other['id'])
    other_client.cookies.set('pa_token', token)
    assert other_client.get('/iphone/api/preferences').json()['continuous_voice'] is True


def test_ui_preferences_reject_unsafe_voice_rate(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.put('/iphone/api/preferences', json={
        'continuous_voice': True,
        'voice_rate': 4,
        'quiet_hours': True,
    })

    assert response.status_code == 422


def test_p3_stage_evidence_endpoint_records_but_does_not_self_award(tmp_path):
    client, _, _ = make_client(tmp_path)
    started = client.post('/iphone/api/qualification/stages', json={
        'stage': 'P3.5',
        'evidence_class': 'real_device',
        'environment': {'os': 'iOS 26.6.1', 'browser': 'Safari'},
    })
    assert started.status_code == 200
    session_id = started.json()['session_id']
    trial = client.post(f'/iphone/api/qualification/sessions/{session_id}/trials', json={
        'task': 'recall owner project',
        'passed': True,
        'latency_ms': 120,
        'metrics': {
            'recall_relevant': True,
            'conflict_resolved': True,
            'temporal_answer_correct': True,
            'source_traceable': True,
            'fabricated_memory': False,
            'deleted_history_on_supersession': False,
        },
        'evidence': {'artifact': 'owner-screen-recording-1'},
    })
    assert trial.status_code == 200
    client.post(f'/iphone/api/qualification/sessions/{session_id}/finish', json={'duration_seconds': 60})
    result = client.get('/iphone/api/qualification').json()['P3.5']
    assert result['trials'] == 1
    assert result['passed'] is False
    assert any('need 50 trials' in item for item in result['failures'])


def test_limited_trusted_device_cannot_read_sensitive_memory_or_private_knowledge(tmp_path):
    owner_client, runtime, _ = make_client(tmp_path)
    sensitive = owner_client.post('/iphone/api/memory', json={
        'type': 'fact',
        'subject': 'Private fact',
        'content': 'Owner-only memory',
        'sensitivity': 'sensitive',
    })
    assert sensitive.status_code == 200
    private = owner_client.post('/iphone/api/knowledge', json={
        'filename': 'private.txt',
        'text': 'Owner-only document',
        'access_class': 'private',
    })
    assert private.status_code == 200

    limited, token = runtime['device_registry'].enroll('Limited browser', 'web')
    limited_client = TestClient(owner_client.app, base_url='https://testserver')
    limited_client.cookies.set('pa_device', limited['id'])
    limited_client.cookies.set('pa_token', token)

    assert limited_client.get('/iphone/api/memory').json()['memories'] == []
    assert limited_client.get('/iphone/api/knowledge').json()['documents'] == []
    assert limited_client.get(f"/iphone/api/memory/{sensitive.json()['id']}").status_code == 404
    assert limited_client.get(f"/iphone/api/knowledge/{private.json()['id']}").status_code == 404
    assert limited_client.post('/iphone/api/memory', json={
        'type': 'fact', 'subject': 'Blocked', 'content': 'Sensitive', 'sensitivity': 'sensitive',
    }).status_code == 403
    assert limited_client.get('/iphone/api/qualification').status_code == 403


def test_legacy_owner_pwa_permissions_migrate_without_new_login(tmp_path):
    path = tmp_path / 'devices.sqlite3'
    registry = DeviceRegistry(path)
    device, token = registry.enroll('Legacy owner iPhone', 'ios-pwa')
    with registry._con() as con:
        con.execute('DELETE FROM device_permissions WHERE device_id=?', (device['id'],))
    restarted = DeviceRegistry(path)
    assert restarted.authenticate(device['id'], token) is True
    assert restarted.authorize(device['id'], 'device:admin') is True


def test_retention_removes_memory_and_vector(tmp_path):
    class Vector:
        def __init__(self): self.deleted = []
        def delete(self, memory_id): self.deleted.append(memory_id)

    store = MemoryStore(tmp_path / 'retention.sqlite3')
    vector = Vector()
    brain = SecondBrain(store, vector_store=vector)
    memory_id = store.remember(type='note', subject='old', content='old', source='test')
    with store.con() as con:
        con.execute("UPDATE memories SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (memory_id,))
    result = brain.apply_retention(older_than_days=1, dry_run=False)
    assert result['matched'] == 1
    assert store.get(memory_id) is None
    assert vector.deleted == [memory_id]


def test_stage8_owner_emergency_stop_cancels_canonical_turns(tmp_path):
    client, runtime, _ = make_client(tmp_path)

    stopped = client.post('/iphone/api/system/emergency-stop', json={'enabled': True})
    assert stopped.status_code == 200
    assert runtime['tools'].emergency_stop is True
    assert runtime['executor'].cancelled == ['emergency_stop']

    resumed = client.post('/iphone/api/system/emergency-stop', json={'enabled': False})
    assert resumed.status_code == 200
    assert runtime['tools'].emergency_stop is False
    assert runtime['executor'].cancelled == ['emergency_stop']


def test_stage8_stale_reauthentication_blocks_security_controls(tmp_path):
    client, runtime, _ = make_client(tmp_path, reauthenticated_at=time.time() - 1000)
    other, _ = runtime['device_registry'].enroll('Other', 'web')

    permissions = client.patch(
        f"/iphone/api/devices/{other['id']}/permissions",
        json={'scopes': ['ai:chat']},
    )
    assert permissions.status_code == 401
    assert permissions.json()['detail']['code'] == 'reauthentication_required'

    revoke = client.post(f"/iphone/api/devices/{other['id']}/revoke", json={'confirm': True})
    assert revoke.status_code == 401
    assert runtime['device_registry'].is_active(other['id']) is True

    runtime['tools'].set_emergency_stop(True)
    release = client.post('/iphone/api/system/emergency-stop', json={'enabled': False})
    assert release.status_code == 401
    assert runtime['tools'].emergency_stop is True

    stop_again = client.post('/iphone/api/system/emergency-stop', json={'enabled': True})
    assert stop_again.status_code == 200
    assert runtime['tools'].emergency_stop is True


def test_stage8_owner_manual_workflow_retry_reuses_one_durable_run(tmp_path):
    client, runtime, _ = make_client(tmp_path)
    created = client.post('/iphone/api/workflows', json={
        'title': 'Idempotent owner run',
        'trigger': {'type': 'manual'},
        'steps': [{'kind': 'set', 'key': 'ok', 'value': True}],
    })
    assert created.status_code == 200
    workflow_id = created.json()['id']

    missing = client.post(f'/iphone/api/workflows/{workflow_id}/run', json={'context': {}})
    assert missing.status_code == 422

    body = {'context': {'source': 'owner-ui'}, 'idempotency_key': 'owner-run-request-0001'}
    first = client.post(f'/iphone/api/workflows/{workflow_id}/run', json=body)
    second = client.post(f'/iphone/api/workflows/{workflow_id}/run', json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()['run_id'] == second.json()['run_id']
    matching = [row for row in runtime['automations'].runs(workflow_id, 20) if row['idempotency_key'] == body['idempotency_key']]
    assert len(matching) == 1


def test_stage8_owner_workflow_payloads_are_bounded(tmp_path):
    client, _, _ = make_client(tmp_path)
    nested = {}
    cursor = nested
    for _ in range(12):
        cursor['next'] = {}
        cursor = cursor['next']

    create = client.post('/iphone/api/workflows', json={
        'title': 'nested',
        'trigger': nested,
        'steps': [{'kind': 'set', 'key': 'ok', 'value': True}],
    })
    assert create.status_code == 413

    valid = client.post('/iphone/api/workflows', json={
        'title': 'valid',
        'trigger': {'type': 'manual'},
        'steps': [{'kind': 'set', 'key': 'ok', 'value': True}],
    })
    assert valid.status_code == 200
    run = client.post(
        f"/iphone/api/workflows/{valid.json()['id']}/run",
        json={'context': nested, 'idempotency_key': 'owner-run-request-0002'},
    )
    assert run.status_code == 413


def test_stage8_owner_structured_metadata_is_bounded(tmp_path):
    client, _, _ = make_client(tmp_path)
    nested = {}
    cursor = nested
    for _ in range(12):
        cursor['next'] = {}
        cursor = cursor['next']

    knowledge = client.post('/iphone/api/knowledge', json={
        'filename': 'bounded.txt',
        'text': 'safe content',
        'metadata': nested,
    })
    assert knowledge.status_code == 413

    qualification = client.post('/iphone/api/qualification/stages', json={
        'stage': 'P3.5',
        'evidence_class': 'real_device',
        'environment': nested,
    })
    assert qualification.status_code == 413


def test_stage8_owner_workflow_read_respects_persisted_device_session_binding(tmp_path):
    client, runtime, owner = make_client(tmp_path)
    owner_token = client.cookies.get('pa_token')
    engine = runtime['automations']
    workflow_id = engine.create_workflow(
        'Stage8 owner-bound visibility',
        {'type': 'manual'},
        [{'kind': 'set', 'key': 'stage8', 'value': 'owner-only-run'}],
    )
    run_id = engine.run_workflow(
        workflow_id,
        background=False,
        owner_id='owner',
        device_id=owner['id'],
        session_id='test-session',
        idempotency_key='stage8-owner-visibility-run',
    )

    own = client.get('/iphone/api/workflows')
    assert own.status_code == 200
    assert run_id in {row['id'] for row in own.json()['runs']}

    foreign, foreign_token = runtime['device_registry'].enroll('Foreign workflow browser', 'web')
    runtime['device_registry'].set_permissions(
        foreign['id'],
        {'workflow:read', 'workflow:approve'},
    )
    client.cookies.set('pa_device', foreign['id'])
    client.cookies.set('pa_token', foreign_token)

    foreign_list = client.get('/iphone/api/workflows')
    assert foreign_list.status_code == 200
    assert run_id not in {row['id'] for row in foreign_list.json()['runs']}

    foreign_approve = client.post(f'/iphone/api/workflows/runs/{run_id}/approve')
    foreign_reject = client.post(f'/iphone/api/workflows/runs/{run_id}/reject')
    for response in (foreign_approve, foreign_reject):
        assert response.status_code == 403
        assert run_id not in response.text
        assert 'not waiting' not in response.text.lower()

    # Positive control: the correctly bound owner gets the real run-state answer.
    client.cookies.set('pa_device', owner['id'])
    client.cookies.set('pa_token', owner_token)
    own_approve = client.post(f'/iphone/api/workflows/runs/{run_id}/approve')
    assert own_approve.status_code == 409
    assert 'not waiting' in own_approve.text.lower()


def test_stage8_owner_workflow_approval_state_hidden_from_foreign_device(tmp_path):
    client, runtime, owner = make_client(tmp_path)
    owner_token = client.cookies.get('pa_token')
    engine = runtime['automations']
    workflow_id = engine.create_workflow(
        'Stage8 owner-bound approval state',
        {'type': 'manual'},
        [{'kind': 'set', 'key': 'stage8', 'value': 'completed'}],
    )
    run_id = engine.run_workflow(
        workflow_id,
        background=False,
        owner_id='owner',
        device_id=owner['id'],
        session_id='test-session',
        idempotency_key='stage8-owner-approval-state',
    )

    foreign, foreign_token = runtime['device_registry'].enroll('Foreign approval browser', 'web')
    runtime['device_registry'].set_permissions(foreign['id'], {'workflow:approve'})
    client.cookies.set('pa_device', foreign['id'])
    client.cookies.set('pa_token', foreign_token)

    approve = client.post(f'/iphone/api/workflows/runs/{run_id}/approve')
    reject = client.post(f'/iphone/api/workflows/runs/{run_id}/reject')
    for response in (approve, reject):
        assert response.status_code == 403
        assert run_id not in response.text
        assert 'not waiting' not in response.text.lower()

    client.cookies.set('pa_device', owner['id'])
    client.cookies.set('pa_token', owner_token)
    own = client.post(f'/iphone/api/workflows/runs/{run_id}/approve')
    assert own.status_code == 409
    assert 'not waiting' in own.text.lower()
