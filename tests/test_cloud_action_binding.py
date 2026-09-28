from __future__ import annotations

from types import SimpleNamespace

from agent.executor import AgentExecutor
from cloud_runtime.relay import SecureCloudRelay
from cloud_runtime.security import CloudSessionStore, OwnerAuthenticator
from core.events import EventBus
from memory.store import MemoryStore
from tools.registry import Risk, Tool, ToolRegistry


class Models:
    def chat(self, *args, **kwargs):
        return 'completed'


class Planner:
    def plan(self, *args, **kwargs):
        return {
            'steps': [
                {
                    'tool': 'dangerous',
                    'parameters': {'recipient': 'person@example.com', 'value': 7},
                    'description': 'send the exact approved action',
                }
            ]
        }


class Devices:
    SCOPES = {'ai:chat', 'device:read', 'memory:read'}

    def authenticate(self, device_id, token):
        return device_id == 'device-1' and token == 'device-secret'

    def is_active(self, device_id):
        return device_id == 'device-1'

    def authorize(self, device_id, scope):
        return self.is_active(device_id) and scope in self.SCOPES


class Events:
    def subscribe(self, *args):
        return lambda: None

    def emit(self, *args, **kwargs):
        pass


def make_relay(tmp_path):
    calls = []
    settings = SimpleNamespace(autonomy_mode='ask', data_dir=tmp_path)
    tools = ToolRegistry(settings)
    tools.register(Tool(
        'dangerous',
        'external action',
        lambda params: calls.append(dict(params)) or {'verified': True},
        Risk.EXTERNAL_SIDE_EFFECT,
    ))
    memory = MemoryStore(tmp_path / 'assistant.sqlite3')
    executor = AgentExecutor(
        models=Models(),
        tools=tools,
        memory=memory,
        events=EventBus(),
    )
    executor.planner = Planner()
    sessions = CloudSessionStore(tmp_path / 'cloud-sessions.sqlite3', ttl_seconds=300)
    relay = SecureCloudRelay(
        executor=executor,
        memory=memory,
        second_brain=None,
        device_registry=Devices(),
        sessions=sessions,
        owner=OwnerAuthenticator('x' * 40),
        events=Events(),
    )
    return relay, calls


def test_cloud_approval_cannot_be_redeemed_from_different_session(tmp_path):
    relay, calls = make_relay(tmp_path)
    first = relay.issue_session('device-1', 'device-secret')
    second = relay.issue_session('device-1', 'device-secret')
    session_1 = relay.sessions.authenticate(first.payload['session_token'], 'ai:chat')
    session_2 = relay.sessions.authenticate(second.payload['session_token'], 'ai:chat')

    proposed = relay.command(session_1, 'do it', 'nonce-not-used-here')
    assert proposed.status == 202
    approval_id = proposed.payload['approval_id']
    assert calls == []

    wrong_session = relay.approval(session_2, approval_id, 'approve')
    assert wrong_session.status == 410
    assert wrong_session.payload['error'] == 'approval_unavailable'
    assert calls == []

    approved = relay.approval(session_1, approval_id, 'approve')
    assert approved.status == 200
    assert approved.payload['reply'] == 'completed'
    assert calls == [{'recipient': 'person@example.com', 'value': 7}]


def test_cloud_command_binds_device_and_session_into_durable_ticket(tmp_path):
    relay, _ = make_relay(tmp_path)
    issued = relay.issue_session('device-1', 'device-secret')
    session = relay.sessions.authenticate(issued.payload['session_token'], 'ai:chat')

    proposed = relay.command(session, 'do it', 'nonce-not-used-here')
    ticket = relay.executor.approvals.ticket(proposed.payload['approval_id'])

    assert ticket is not None
    assert ticket.owner_id == 'owner'
    assert ticket.device_id == 'device-1'
    assert ticket.session_id == session.id
    assert ticket.destination == 'person@example.com'
    assert ticket.data_classification == 'internal'


def test_cloud_emergency_stop_invalidates_approval_after_stop_is_cleared(tmp_path):
    relay, calls = make_relay(tmp_path)
    issued = relay.issue_session('device-1', 'device-secret')
    session = relay.sessions.authenticate(issued.payload['session_token'], 'ai:chat')

    proposed = relay.command(session, 'do it', 'nonce-not-used-here')
    approval_id = proposed.payload['approval_id']
    assert relay.executor.approval_context(approval_id) is not None

    stopped = relay.set_emergency_stop('x' * 40, True)
    assert stopped.status == 200
    assert relay.executor.tools.emergency_stop is True
    assert relay.executor.approval_context(approval_id) is None

    cleared = relay.set_emergency_stop('x' * 40, False)
    assert cleared.status == 200
    assert relay.executor.tools.emergency_stop is False
    stale = relay.approval(session, approval_id, 'approve')
    assert stale.status == 410
    assert stale.payload['error'] == 'approval_unavailable'
    assert calls == []
