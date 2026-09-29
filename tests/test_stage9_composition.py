"""Stage 9 composition harness H1–H12.

These call the canonical authorities. They do not replace the Stage 8 tests.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from automation.engine import AutomationEngine, now
from devices.continuity import ContinuityService
from knowledge.store import KnowledgeStore
from recovery.backup import BackupError, BackupService
from security.approvals import ApprovalManager
from server.api import create_app
from test_stage8_never_store_and_sheets_parity import SENTINEL, durable_counts, make_client
from test_v10_recovery import StaticRootKeyStore


class _CountingExecutor:
    def __init__(self):
        self.calls = 0

    def chat(self, text):
        self.calls += 1
        return 'should-not-run:' + text


def _relay(tmp_path, executor):
    from cloud_runtime.relay import SecureCloudRelay
    from cloud_runtime.security import CloudSessionStore, OwnerAuthenticator

    class Devices:
        def authenticate(self, device_id, token):
            return device_id == 'dev1' and token == 'device-secret'

        def is_active(self, device_id):
            return device_id == 'dev1'

        def authorize(self, device_id, scope):
            return self.is_active(device_id) and scope in {'ai:chat', 'approval:write'}

    class Memory:
        def audit(self, *args):
            return None

        def search(self, q, limit=20):
            return []

    class Events:
        def subscribe(self, *args):
            return lambda: None

        def emit(self, *args, **kwargs):
            return None

    sessions = CloudSessionStore(tmp_path / 'sessions.sqlite3', ttl_seconds=60)
    return SecureCloudRelay(
        executor=executor,
        memory=Memory(),
        second_brain=None,
        device_registry=Devices(),
        sessions=sessions,
        owner=OwnerAuthenticator('x' * 40),
        events=Events(),
    )


def test_h1_emergency_stop_blocks_cloud_command_without_side_effect(tmp_path):
    executor = _CountingExecutor()
    relay = _relay(tmp_path, executor)
    issued = relay.issue_session('dev1', 'device-secret')
    session = relay.sessions.authenticate(issued.payload['session_token'], 'ai:chat')
    assert relay.set_emergency_stop('x' * 40, True).status == 200
    blocked = relay.command(session, 'hello', '0123456789abcdef')
    assert blocked.status == 423
    assert executor.calls == 0


def test_h2_emergency_stop_marks_running_workflow_recovery_required(tmp_path):
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=None, events=None)
    workflow_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    stamp = now()
    with engine._con() as con:
        con.execute(
            '''INSERT INTO workflows(id,title,trigger_json,steps_json,enabled,paused,next_run_at,interval_seconds,created_at,updated_at,last_run_at,policy_json)
               VALUES(?,?,?,?,1,0,NULL,NULL,?,?,NULL,?)''',
            (workflow_id, 'running', '{}', '[]', stamp, stamp, '{}'),
        )
        con.execute(
            '''INSERT INTO workflow_runs(
                id,workflow_id,status,trigger_json,context_json,current_step,completed_steps_json,
                result_json,error,pending_approval_id,started_at,updated_at,completed_at)
               VALUES(?,?,?,?,?,0,'[]',NULL,NULL,NULL,?,?,NULL)''',
            (run_id, workflow_id, 'running', '{}', '{}', stamp, stamp),
        )
    engine._halt_for_emergency_stop()
    run = engine._run(run_id)
    assert run['status'] == 'recovery_required'
    assert 'emergency stop' in str(run.get('error') or '').lower()


def test_h3_revoked_source_cannot_activate_handoff_target(tmp_path):
    service = ContinuityService(tmp_path / 'continuity.sqlite3')
    thread_id = service.create_thread('owner thread', device_id='source')

    def revoked():
        raise PermissionError('device revoked')

    with pytest.raises(PermissionError):
        service.handoff(thread_id, from_device='source', to_device='target', authority_guard=revoked)
    with service._con() as con:
        target = con.execute(
            'SELECT active_thread_id FROM continuity_device_state WHERE device_id=?',
            ('target',),
        ).fetchone()
    assert target is None


def test_h4_connector_knowledge_without_write_scope_has_no_rows(tmp_path):
    client, _knowledge, drive, _sheets, store = make_client(tmp_path, {'device:admin'})
    response = client.post(
        '/iphone/api/connectors/drive/files/file-1/knowledge',
        json={'approved': True, 'access_class': 'owner'},
    )
    assert response.status_code == 403
    assert drive.read_count == 0
    assert durable_counts(store)['documents'] == 0


def test_h5_connector_knowledge_unapproved_has_no_durable_effect(tmp_path):
    client, _knowledge, drive, _sheets, store = make_client(
        tmp_path, {'knowledge:write', 'device:read'}
    )
    response = client.post(
        '/iphone/api/connectors/drive/files/file-1/knowledge',
        json={'approved': False, 'access_class': 'owner'},
    )
    assert response.status_code == 409
    assert drive.read_count == 0
    assert durable_counts(store)['documents'] == 0
    assert SENTINEL.encode() not in (tmp_path / 'knowledge.sqlite3').read_bytes()


def test_h6_private_ingest_without_private_scope_has_no_durable_effect(tmp_path):
    client, _knowledge, drive, _sheets, store = make_client(tmp_path, {'knowledge:write'})
    response = client.post(
        '/iphone/api/connectors/drive/files/file-1/knowledge',
        json={'approved': True, 'access_class': 'private'},
    )
    assert response.status_code == 403
    assert drive.read_count == 0
    assert durable_counts(store)['documents'] == 0


def test_h7_workflow_runs_without_binding_fail_closed(tmp_path):
    class Registry:
        def authenticate(self, device_id, token):
            return device_id == 'device-1' and token == 'token-1'

        def authorize(self, device_id, scope):
            return scope == 'workflow:read'

    class Engine:
        def runs(self, workflow_id=None, limit=100):
            return [{'id': 'run-secret', 'result_json': '{"secret": true}'}]

    settings = SimpleNamespace(pairing_ttl_seconds=60, cloud_runtime_enabled=False, data_dir=tmp_path)
    app = create_app(
        SimpleNamespace(),
        settings,
        device_registry=Registry(),
        runtime={'automations': Engine()},
    )
    client = TestClient(app)
    response = client.get(
        '/workflows/runs',
        headers={'Authorization': 'Bearer token-1', 'X-Device-ID': 'device-1'},
    )
    assert response.status_code == 503
    assert 'run-secret' not in response.text


def test_h8_default_knowledge_search_excludes_private(tmp_path):
    store = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    store.ingest(filename='owner-note.txt', data=b'owner-visible-token', access_class='owner')
    store.ingest(filename='private-note.txt', data=b'private-hidden-token', access_class='private')
    # Default owner search classes when the device lacks knowledge:private.
    visible = store.search('token', access_classes={'owner', 'trusted-devices'})
    blob = json.dumps(visible)
    assert 'owner-visible-token' in blob
    assert 'private-hidden-token' not in blob
    assert all(row['access_class'] != 'private' for row in visible)


def test_h9_workflow_tool_step_cannot_dispatch_without_authority(tmp_path):
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=_CountingExecutor(), events=None)
    with pytest.raises(ValueError, match='unsupported workflow step kind: tool'):
        engine.create_workflow(
            'launder',
            {'type': 'manual'},
            [{'kind': 'tool', 'tool_name': 'desktop.open', 'parameters': {'path': '/etc/passwd'}}],
        )
    assert engine.workflows() == []
    assert engine.executor.calls == 0


def test_h10_hostile_restore_parent_symlink_creates_nothing_outside(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    data.mkdir()
    nested = data / 'docs'
    nested.mkdir()
    (nested / 'note.txt').write_text('owner-state', encoding='utf-8')
    outside = tmp_path / 'outside'
    outside.mkdir()
    service = BackupService(data, root_key_store=StaticRootKeyStore(b'k' * 32))
    archive = service.create('h10.paibackup')
    target = tmp_path / 'restore-target'
    target.mkdir()
    (target / 'docs').mkdir()
    service.data_dir = target.resolve()
    service.backup_dir = target / 'backups'
    service.backup_dir.mkdir(exist_ok=True)
    real_safe = service._safe_destination
    swapped = {'done': False}

    def swap_then_safe(rel):
        destination = real_safe(rel)
        parent = destination.parent
        if (
            not swapped['done']
            and parent != target
            and parent.exists()
            and parent.name == 'docs'
            and not parent.is_symlink()
        ):
            parent.rename(target / 'docs-real')
            parent.symlink_to(outside, target_is_directory=True)
            swapped['done'] = True
        return destination

    monkeypatch.setattr(service, '_safe_destination', swap_then_safe)
    before = {path.name for path in outside.iterdir()}
    with pytest.raises(BackupError):
        service.restore(archive)
    after = {path.name for path in outside.iterdir()}
    assert swapped['done'] is True
    assert after == before


def test_h11_verified_false_is_not_pure_success(tmp_path):
    store = ApprovalManager(path=tmp_path / 'approvals.sqlite3')
    ticket = store.create(
        execution_id='exec-h11',
        tool_name='desktop.open',
        parameters={'path': '/tmp/demo'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.approve(
        ticket.id,
        execution_id='exec-h11',
        tool_name='desktop.open',
        parameters={'path': '/tmp/demo'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.begin_dispatch(ticket.id, worker_id='worker-1')
    outcome = store.complete_dispatch(
        ticket.id,
        {'status': 'completed', 'verified': False, 'failure_code': 'effect_unconfirmed'},
    )
    assert outcome.get('verified') is False
    assert outcome.get('failure_code') == 'effect_unconfirmed'
    record = store.record(ticket.id)
    assert record['outcome']['verified'] is False


def test_h12_security_epoch_advance_blocks_prior_ticket(tmp_path):
    store = ApprovalManager(path=tmp_path / 'approvals.sqlite3')
    ticket = store.create(
        execution_id='exec-h12',
        tool_name='desktop.open',
        parameters={'path': '/tmp/z'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.approve(
        ticket.id,
        execution_id='exec-h12',
        tool_name='desktop.open',
        parameters={'path': '/tmp/z'},
        owner_id='owner',
        device_id='device-1',
        session_id='session-1',
    )
    store.advance_security_epoch()
    result = store.begin_dispatch(ticket.id, worker_id='worker-1')
    assert result['dispatch'] is False
    assert result['status'] in {'invalidated', 'recovery_required'}
