"""Stage 9: the durable Emergency Stop is the tool registry, not the cloud mirror."""

from types import SimpleNamespace

from cloud_runtime.relay import SecureCloudRelay
from cloud_runtime.security import CloudSessionStore, OwnerAuthenticator
from tools.registry import ToolRegistry


class _Devices:
    def authenticate(self, device_id, token):
        return device_id == 'dev1' and token == 'device-secret'

    def is_active(self, device_id):
        return device_id == 'dev1'

    def authorize(self, device_id, scope):
        return scope == 'ai:chat'


class _Memory:
    def audit(self, *args):
        return None


class _Events:
    def subscribe(self, *args):
        return lambda: None

    def emit(self, *args, **kwargs):
        return None


class _Executor:
    def __init__(self, tools):
        self.tools = tools
        self.calls = 0

    def chat(self, text, **kwargs):
        self.calls += 1
        return 'ran:' + text


def _relay(tmp_path, tools):
    return SecureCloudRelay(
        executor=_Executor(tools),
        memory=_Memory(),
        second_brain=None,
        device_registry=_Devices(),
        sessions=CloudSessionStore(tmp_path / 'sessions.sqlite3', ttl_seconds=60),
        owner=OwnerAuthenticator('x' * 40),
        events=_Events(),
    )


def test_stage9_restarted_tool_registry_keeps_emergency_stop(tmp_path):
    settings = SimpleNamespace(autonomy_mode='ask', data_dir=tmp_path)
    ToolRegistry(settings).set_emergency_stop(True)
    restarted = ToolRegistry(settings)
    assert restarted.emergency_stop is True
    relay = _relay(tmp_path, restarted)
    assert relay.sessions.emergency_stopped() is False
    issued = relay.issue_session('dev1', 'device-secret')
    session = relay.sessions.authenticate(issued.payload['session_token'], 'ai:chat')
    blocked = relay.command(session, 'hello', '0123456789abcdef')
    assert blocked.status == 423
    assert relay.executor.calls == 0
    relay.sessions.set_emergency_stop(False)
    assert relay.command(session, 'still stopped', 'abcdef0123456789').status == 423


def test_stage9_cloud_stop_is_durable_in_the_tool_registry(tmp_path):
    settings = SimpleNamespace(autonomy_mode='ask', data_dir=tmp_path)
    tools = ToolRegistry(settings)
    relay = _relay(tmp_path, tools)
    assert relay.set_emergency_stop('x' * 40, True).status == 200
    assert ToolRegistry(settings).emergency_stop is True
    assert relay.sessions.emergency_stopped() is True
    cleared = relay.set_emergency_stop('x' * 40, False)
    assert cleared.status == 200
    assert ToolRegistry(settings).emergency_stop is False
    assert relay.sessions.emergency_stopped() is False
