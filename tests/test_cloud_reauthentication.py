from __future__ import annotations

from agent.executor import ReauthenticationRequired
from cloud_runtime.relay import SecureCloudRelay
from cloud_runtime.security import CloudSessionStore, OwnerAuthenticator


class Memory:
    def __init__(self):
        self.audit_rows = []

    def audit(self, *args):
        self.audit_rows.append(args)

    def search(self, *args, **kwargs):
        return []


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


class Executor:
    def __init__(self):
        self.calls = []
        self.require_reauth = False

    def chat(self, text, **kwargs):
        self.calls.append(('chat', kwargs))
        if self.require_reauth and kwargs.get('reauthenticated_at') is None:
            raise ReauthenticationRequired('critical', execution_id='execution-1')
        return 'reply'

    def approve(self, approval_id, **kwargs):
        self.calls.append(('approve', kwargs))
        if self.require_reauth and kwargs.get('reauthenticated_at') is None:
            raise ReauthenticationRequired('critical', execution_id='execution-1')
        return 'approved'

    def reject(self, approval_id, **kwargs):
        return 'rejected'


def make_relay(tmp_path):
    executor = Executor()
    sessions = CloudSessionStore(tmp_path / 'cloud.sqlite3', ttl_seconds=600)
    relay = SecureCloudRelay(
        executor=executor,
        memory=Memory(),
        second_brain=None,
        device_registry=Devices(),
        sessions=sessions,
        owner=OwnerAuthenticator('x' * 40),
        events=Events(),
    )
    return relay, executor


def test_cloud_critical_action_returns_reauth_required_then_succeeds(tmp_path):
    relay, executor = make_relay(tmp_path)
    issued = relay.issue_session('device-1', 'device-secret')
    token = issued.payload['session_token']
    session = relay.sessions.authenticate(token, 'ai:chat')
    executor.require_reauth = True

    blocked = relay.command(session, 'critical action', 'not-used-here')
    assert blocked.status == 401
    assert blocked.payload['error'] == 'reauthentication_required'

    verified = relay.reauthenticate(session, 'x' * 40)
    assert verified.status == 200
    refreshed = relay.sessions.authenticate(token, 'ai:chat')
    assert refreshed.reauthenticated_at is not None

    completed = relay.command(refreshed, 'critical action', 'not-used-here')
    assert completed.status == 200
    assert executor.calls[-1][1]['reauthenticated_at'] == refreshed.reauthenticated_at


def test_cloud_reauthentication_rejects_wrong_owner_secret(tmp_path):
    relay, _ = make_relay(tmp_path)
    issued = relay.issue_session('device-1', 'device-secret')
    session = relay.sessions.authenticate(issued.payload['session_token'], 'status:read')

    result = relay.reauthenticate(session, 'wrong')
    assert result.status == 401
    assert result.payload['error'] == 'owner_auth_failed'
    assert relay.sessions.session(session.id).reauthenticated_at is None
