from pathlib import Path
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.events import EventBus
from agent.executor import ConfirmationRequired
from devices.continuity import ContinuityService
from server.iphone_pwa import iphone_pwa_router
from models.router import ModelTimeout, ModelUnavailable
from security.owner_access import OwnerAccessStore
from security.pwa_sessions import PwaSessionStore
from server.pwa_session_middleware import PwaSessionMiddleware


class Registry:
    def __init__(self):
        self.tokens = {}
        self.active = set()
        self.sequence = 0
    def enroll(self, name, platform):
        self.sequence += 1
        device_id = f'iphone-{self.sequence}'
        token = f'token-{self.sequence}'
        self.tokens[device_id] = token
        self.active.add(device_id)
        return {'id': device_id, 'name': name, 'platform': platform}, token
    def authenticate(self, device_id, token):
        return self.tokens.get(device_id) == token
    def is_active(self, device_id):
        return device_id in self.active


class Executor:
    def chat(self, text, cancel_event=None, device_id=None, conversation_id=None, conversation_history=None):
        return f'reply:{text}:{device_id}'


class Recorder:
    def __init__(self):
        self.started = False
        self.environment = None
    def start_session(self, **kwargs):
        if self.started:
            raise RuntimeError('voice qualification session already active')
        self.started = True
        self.kwargs = kwargs
        self.environment = kwargs.get('environment')
        return 'session-1'
    def active_session(self):
        if not self.started:
            return None
        return {
            'id': 'session-1',
            'evidence_class': 'real_device',
            'environment': self.environment or {},
        }
    def stop_session(self):
        if not self.started:
            raise RuntimeError('no active voice qualification session')
        self.started = False
        return {'turns': 1, 'barge_trials': 0, 'barge_success_rate': 0.0, 'passed': False}
    def close_active_sessions(self, *, reason):
        closed = ['session-1'] if self.started else []
        self.started = False
        self.closed_reason = reason
        return closed
    def sessions(self):
        return [{'id': 'session-1'}]


def make_client(tmp_path: Path, allow_insecure=False, google_signin=False, server_sessions=False, include_legacy_runtime_routes=True):
    settings = SimpleNamespace(
        base_dir=Path(__file__).resolve().parent.parent,
        iphone_owner_enrollment_code='this-is-a-long-owner-code',
        iphone_pwa_allow_insecure=allow_insecure,
        google_signin_client_id='google-client.apps.googleusercontent.com' if google_signin else '',
        owner_google_email='owner@example.com' if google_signin else '',
    )
    events = EventBus()
    runtime = {
        'device_registry': Registry(),
        'executor': Executor(),
        'events': events,
        'continuity': ContinuityService(tmp_path / 'continuity.sqlite3', events=events),
        'voice_qualification': Recorder(),
        'owner_access': OwnerAccessStore(tmp_path / 'owner-access.sqlite3'),
    }
    if server_sessions:
        runtime['pwa_sessions'] = PwaSessionStore(tmp_path / 'pwa-sessions.sqlite3', ttl_seconds=600)
    app = FastAPI()
    if server_sessions:
        app.add_middleware(
            PwaSessionMiddleware,
            sessions=runtime['pwa_sessions'],
            device_registry=runtime['device_registry'],
            cookie_max_age=600,
        )
    app.include_router(iphone_pwa_router(runtime, settings, include_legacy_runtime_routes=include_legacy_runtime_routes))
    return TestClient(app, base_url='https://testserver'), runtime


def test_production_router_can_exclude_legacy_canonical_runtime_overlaps(tmp_path):
    client, _ = make_client(tmp_path, include_legacy_runtime_routes=False)
    enrolled = client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    assert enrolled.status_code == 200

    # These method/path signatures are owned by the Stage 2/3 canonical routers
    # in cloud_app. Inspect the actual route table because a legitimate
    # non-overlapping method on the same path can correctly produce HTTP 405.
    registered = {
        (method, getattr(route, 'path', ''))
        for route in client.app.routes
        for method in (getattr(route, 'methods', None) or ())
    }
    forbidden = {
        ('POST', '/iphone/api/voice/turn'),
        ('POST', '/iphone/api/approval/{approval_id}/approve'),
        ('POST', '/iphone/api/approval/{approval_id}/reject'),
        ('GET', '/iphone/api/conversations'),
        ('GET', '/iphone/api/conversations/{conversation_id}'),
        ('POST', '/iphone/api/voice/barge'),
        ('POST', '/iphone/api/voice/client-event'),
    }
    assert registered.isdisjoint(forbidden)

    # Non-overlapping owner-access routes remain available.
    assert client.get('/iphone/api/status').status_code == 200


def test_owner_enrollment_requires_correct_code_and_sets_secure_cookies(tmp_path):
    client, _ = make_client(tmp_path)
    bad = client.post('/iphone/api/enroll', json={'code': 'wrong'})
    assert bad.status_code == 401
    response = client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    assert response.status_code == 200
    assert response.json()['device_id'] == 'iphone-1'
    cookies = response.headers.get_list('set-cookie')
    assert any('pa_device=' in c and 'HttpOnly' in c and 'Secure' in c and 'SameSite=strict' in c for c in cookies)
    assert any('pa_token=' in c and 'HttpOnly' in c and 'Secure' in c and 'SameSite=strict' in c for c in cookies)
    assert all('Max-Age=31536000' in c for c in cookies)


def test_status_renews_existing_browser_trust_without_reenrollment(tmp_path):
    client, runtime = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})

    response = client.get('/iphone/api/status')

    assert response.status_code == 200
    cookies = response.headers.get_list('set-cookie')
    assert len(cookies) == 2
    assert all('Max-Age=31536000' in cookie for cookie in cookies)
    assert len(runtime['device_registry'].tokens) == 1


def test_owner_password_unlocks_a_new_browser_after_trusted_setup(tmp_path):
    client, _ = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    assert client.post('/iphone/api/access/password/setup', json={
        'password': 'correct horse battery staple',
    }).status_code == 200
    client.post('/iphone/api/logout', json={})

    assert client.post('/iphone/api/access/password/login', json={
        'password': 'wrong password',
    }).status_code == 401
    login = client.post('/iphone/api/access/password/login', json={
        'password': 'correct horse battery staple',
        'name': 'Safari with password',
    })
    assert login.status_code == 200
    assert client.get('/iphone/api/status').status_code == 200


def test_recovery_code_unlocks_once_and_cannot_be_replayed(tmp_path):
    client, _ = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    generated = client.post('/iphone/api/access/recovery/regenerate', json={}).json()['codes']
    client.post('/iphone/api/logout', json={})

    assert client.post('/iphone/api/access/recovery/login', json={'code': generated[0]}).status_code == 200
    client.post('/iphone/api/logout', json={})
    assert client.post('/iphone/api/access/recovery/login', json={'code': generated[0]}).status_code == 401


def test_access_options_and_passkey_registration_require_owner_trust(tmp_path):
    client, _ = make_client(tmp_path)
    options = client.get('/iphone/api/access/options').json()
    assert options == {
        'passkey_available': False,
        'password_available': False,
        'recovery_available': False,
        'enrollment_available': True,
        'google_available': False,
        'google_client_id': '',
    }
    assert client.post('/iphone/api/access/passkey/register/options', json={}).status_code == 401
    assert client.post('/iphone/api/access/passkey/login/options', json={}).status_code == 409

    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    registration = client.post('/iphone/api/access/passkey/register/options', json={})
    assert registration.status_code == 200
    public_key = registration.json()['public_key']
    assert public_key['rp']['id'] == 'testserver'
    assert public_key['authenticatorSelection']['userVerification'] == 'required'


def test_password_failures_are_rate_limited(tmp_path):
    client, _ = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    client.post('/iphone/api/access/password/setup', json={'password': 'correct horse battery staple'})
    client.post('/iphone/api/logout', json={})
    for _ in range(5):
        assert client.post('/iphone/api/access/password/login', json={'password': 'wrong'}).status_code == 401
    assert client.post('/iphone/api/access/password/login', json={'password': 'wrong'}).status_code == 429


def test_verified_configured_google_owner_unlocks_new_browser(tmp_path, monkeypatch):
    client, runtime = make_client(tmp_path, google_signin=True)
    calls = []

    def verify(token, request, audience):
        calls.append((token, audience))
        return {
            'sub': 'google-owner-subject',
            'email': 'OWNER@example.com',
            'email_verified': True,
        }

    monkeypatch.setattr('server.iphone_pwa.google_id_token.verify_oauth2_token', verify)
    options = client.get('/iphone/api/access/options').json()
    assert options['google_available'] is True
    assert options['google_client_id'] == 'google-client.apps.googleusercontent.com'

    response = client.post('/iphone/api/access/google/login', json={
        'credential': 'g' * 120,
        'name': 'Owner Google Safari',
    })

    assert response.status_code == 200
    assert calls == [('g' * 120, 'google-client.apps.googleusercontent.com')]
    assert client.get('/iphone/api/status').status_code == 200
    assert runtime['device_registry'].tokens['iphone-1'] == 'token-1'
    cookies = response.headers.get_list('set-cookie')
    assert all('HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie for cookie in cookies)


def test_google_login_rejects_other_or_unverified_accounts(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, google_signin=True)

    monkeypatch.setattr(
        'server.iphone_pwa.google_id_token.verify_oauth2_token',
        lambda *_: {'sub': 'someone-else', 'email': 'other@example.com', 'email_verified': True},
    )
    assert client.post('/iphone/api/access/google/login', json={'credential': 'x' * 120}).status_code == 401

    monkeypatch.setattr(
        'server.iphone_pwa.google_id_token.verify_oauth2_token',
        lambda *_: {'sub': 'owner', 'email': 'owner@example.com', 'email_verified': False},
    )
    assert client.post('/iphone/api/access/google/login', json={'credential': 'y' * 120}).status_code == 401


def test_google_login_fails_closed_when_not_configured(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.post('/iphone/api/access/google/login', json={'credential': 'x' * 120})
    assert response.status_code == 503


def test_voice_turn_uses_enrolled_device_and_existing_executor(tmp_path):
    client, _ = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    response = client.post('/iphone/api/voice/turn', json={'transcript': 'hello'})
    assert response.status_code == 200
    assert response.json()['reply'] == 'reply:hello:iphone-1'


def test_voice_tool_request_returns_owner_approval_instead_of_http_500(tmp_path):
    client, runtime = make_client(tmp_path)

    class ApprovalExecutor:
        def chat(self, text, cancel_event=None, device_id=None, conversation_id=None, conversation_history=None):
            raise ConfirmationRequired(
                'web_search_browser',
                {'query': text},
                'Search the web for the requested information',
                approval_id='approval-1',
                execution_id='execution-1',
                expires_at=12345.0,
            )

        def approve(self, approval_id):
            assert approval_id == 'approval-1'
            return 'The approved search completed.'

        def reject(self, approval_id):
            assert approval_id == 'approval-1'
            return 'Action cancelled.'

    runtime['executor'] = ApprovalExecutor()
    app = FastAPI()
    app.include_router(iphone_pwa_router(runtime, SimpleNamespace(
        base_dir=Path(__file__).resolve().parent.parent,
        iphone_owner_enrollment_code='this-is-a-long-owner-code',
        iphone_pwa_allow_insecure=False,
    )))
    client = TestClient(app, base_url='https://testserver')
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})

    response = client.post('/iphone/api/voice/turn', json={'transcript': 'search the web'})

    assert response.status_code == 202
    assert response.json()['status'] == 'approval_required'
    assert response.json()['approval']['tool'] == 'web_search_browser'
    assert 'query' not in response.json()['approval']
    approved = client.post('/iphone/api/approval/approval-1/approve', json={})
    assert approved.status_code == 200
    assert approved.json()['reply'] == 'The approved search completed.'


def test_pwa_approval_recovers_from_ephemeral_cache_loss_using_canonical_context(tmp_path):
    client, runtime = make_client(tmp_path)

    class DurableApprovalExecutor:
        def __init__(self):
            self.pending = False

        def chat(self, text, cancel_event=None, device_id=None, conversation_id=None, conversation_history=None):
            self.pending = True
            raise ConfirmationRequired(
                'web_search_browser',
                {'query': text},
                'Search the web for the requested information',
                approval_id='approval-durable',
                execution_id='execution-durable',
                expires_at=12345.0,
            )

        def approval_context(self, approval_id):
            if self.pending and approval_id == 'approval-durable':
                return {
                    'approval_id': approval_id,
                    'device_id': 'iphone-1',
                    'conversation_id': None,
                    'tool': 'web_search_browser',
                }
            return None

        def approve(self, approval_id):
            assert approval_id == 'approval-durable'
            self.pending = False
            return 'Recovered durable approval completed.'

        def reject(self, approval_id):
            self.pending = False
            return 'Action cancelled.'

    executor = DurableApprovalExecutor()
    runtime['executor'] = executor
    settings = SimpleNamespace(
        base_dir=Path(__file__).resolve().parent.parent,
        iphone_owner_enrollment_code='this-is-a-long-owner-code',
        iphone_pwa_allow_insecure=False,
    )
    app = FastAPI()
    app.include_router(iphone_pwa_router(runtime, settings))
    client = TestClient(app, base_url='https://testserver')
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    pending = client.post('/iphone/api/voice/turn', json={'transcript': 'search the web'})
    assert pending.status_code == 202

    # Recreate the router to simulate process/router-local cache loss while the
    # canonical durable approval remains pending.
    reloaded = FastAPI()
    reloaded.include_router(iphone_pwa_router(runtime, settings))
    reloaded_client = TestClient(reloaded, base_url='https://testserver')
    reloaded_client.cookies.update(client.cookies)
    approved = reloaded_client.post('/iphone/api/approval/approval-durable/approve', json={})
    assert approved.status_code == 200
    assert approved.json()['reply'] == 'Recovered durable approval completed.'


def test_pwa_approval_cache_cannot_cross_device_binding(tmp_path):
    client, runtime = make_client(tmp_path)

    class BoundApprovalExecutor:
        def approval_context(self, approval_id):
            return {
                'approval_id': approval_id,
                'device_id': 'different-device',
                'conversation_id': None,
                'tool': 'web_search_browser',
            }

        def approve(self, approval_id):
            raise AssertionError('cross-device approval must not execute')

    runtime['executor'] = BoundApprovalExecutor()
    settings = SimpleNamespace(
        base_dir=Path(__file__).resolve().parent.parent,
        iphone_owner_enrollment_code='this-is-a-long-owner-code',
        iphone_pwa_allow_insecure=False,
    )
    app = FastAPI()
    app.include_router(iphone_pwa_router(runtime, settings))
    client = TestClient(app, base_url='https://testserver')
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    response = client.post('/iphone/api/approval/approval-durable/approve', json={})
    assert response.status_code == 404


def test_unavailable_tool_returns_safe_error_instead_of_http_500(tmp_path):
    client, runtime = make_client(tmp_path)

    class BrokenToolExecutor:
        def chat(self, *args, **kwargs):
            raise RuntimeError('Library libxcb.so not found at internal path')

    runtime['executor'] = BrokenToolExecutor()
    app = FastAPI()
    app.include_router(iphone_pwa_router(runtime, SimpleNamespace(
        base_dir=Path(__file__).resolve().parent.parent,
        iphone_owner_enrollment_code='this-is-a-long-owner-code',
        iphone_pwa_allow_insecure=False,
    )))
    client = TestClient(app, base_url='https://testserver')
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})

    response = client.post('/iphone/api/voice/turn', json={'transcript': 'look at the server screen'})

    assert response.status_code == 502
    assert response.json()['detail']['code'] == 'tool_error'
    assert 'libxcb' not in response.text


def test_cancelled_http_error_is_not_reclassified_as_tool_error(tmp_path):
    client, runtime = make_client(tmp_path)

    class CancelledExecutor:
        def chat(self, text, cancel_event=None, **kwargs):
            cancel_event.set()
            return 'stale reply'

    runtime['executor'] = CancelledExecutor()
    app = FastAPI()
    app.include_router(iphone_pwa_router(runtime, SimpleNamespace(
        base_dir=Path(__file__).resolve().parent.parent,
        iphone_owner_enrollment_code='this-is-a-long-owner-code',
        iphone_pwa_allow_insecure=False,
    )))
    client = TestClient(app, base_url='https://testserver')
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    response = client.post('/iphone/api/voice/turn', json={'transcript': 'cancel'})
    assert response.status_code == 409
    assert response.json()['detail'] == 'turn_cancelled'


def test_p3_session_records_ios_pwa_environment_but_does_not_self_award(tmp_path):
    client, runtime = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    start = client.post('/iphone/api/qualification/start', json={'environment': {'noise': 'quiet'}})
    assert start.status_code == 200
    recorder = runtime['voice_qualification']
    assert recorder.kwargs['evidence_class'] == 'real_device'
    assert recorder.kwargs['environment']['platform'] == 'ios-pwa'
    stop = client.post('/iphone/api/qualification/stop', json={})
    assert stop.status_code == 200
    assert stop.json()['passed'] is False


def test_second_stop_is_idempotent_and_user_safe(tmp_path):
    client, _ = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    client.post('/iphone/api/qualification/start', json={'environment': {}})
    assert client.post('/iphone/api/qualification/stop', json={}).status_code == 200
    second = client.post('/iphone/api/qualification/stop', json={})
    assert second.status_code == 200
    assert second.json() == {
        'ok': True,
        'status': 'already_stopped',
        'message': 'Session already stopped',
    }


def test_repeated_start_resumes_active_session_after_page_refresh(tmp_path):
    client, _ = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    first = client.post('/iphone/api/qualification/start', json={'environment': {'noise': 'quiet'}})
    assert first.status_code == 200
    assert first.json()['status'] == 'started'

    resumed = client.post('/iphone/api/qualification/start', json={'environment': {'noise': 'quiet'}})
    assert resumed.status_code == 200
    assert resumed.json() == {
        'session_id': 'session-1',
        'evidence_class': 'real_device',
        'status': 'already_active',
        'message': 'Existing session resumed',
    }


def test_status_restores_the_active_session_for_hands_free_ui(tmp_path):
    client, _ = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    client.post('/iphone/api/qualification/start', json={'environment': {}})

    status = client.get('/iphone/api/status')

    assert status.status_code == 200
    assert status.json()['active_qualification']['session_id'] == 'session-1'


def test_trusted_owner_can_explicitly_replace_other_device_stale_session(tmp_path):
    client, runtime = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    recorder = runtime['voice_qualification']
    recorder.started = True
    recorder.environment = {'device_id': 'old-browser'}

    blocked = client.post('/iphone/api/qualification/start', json={'environment': {}})
    assert blocked.status_code == 409
    takeover = client.post('/iphone/api/qualification/takeover', json={
        'confirm': True,
        'environment': {'noise': 'quiet'},
    })

    assert takeover.status_code == 200
    assert takeover.json()['closed_session_ids'] == ['session-1']
    assert recorder.environment['device_id'] == 'iphone-1'
    assert 'Owner-confirmed takeover' in recorder.closed_reason


def test_home_uses_one_touch_voice_instead_of_four_test_buttons(tmp_path):
    client, _ = make_client(tmp_path)
    page = client.get('/iphone/')

    assert page.status_code == 200
    assert 'id="micButton"' in page.text
    assert 'Tap once to talk continuously' in page.text
    assert '>Start Session<' not in page.text
    assert '>Start Listening<' not in page.text
    assert '>Interrupt<' not in page.text
    assert 'Continue here' in page.text


def test_client_tts_failure_is_recorded_as_voice_error(tmp_path):
    client, runtime = make_client(tmp_path)
    errors = []
    runtime['events'].subscribe('voice.error', errors.append)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    client.post('/iphone/api/qualification/start', json={'environment': {}})

    response = client.post('/iphone/api/voice/client-event', json={
        'event': 'tts_error',
        'detail': 'start_timeout',
    })

    assert response.status_code == 200
    assert errors[0]['error'] == 'tts_error'
    assert errors[0]['detail'] == 'start_timeout'


def test_model_unavailable_is_a_safe_explicit_state(tmp_path):
    client, runtime = make_client(tmp_path)

    class UnavailableExecutor:
        def chat(self, *args, **kwargs):
            raise ModelUnavailable('connection refused', provider='self_hosted')

    runtime['executor'] = UnavailableExecutor()
    app = FastAPI()
    app.include_router(iphone_pwa_router(runtime, SimpleNamespace(
        base_dir=Path(__file__).resolve().parent.parent,
        iphone_owner_enrollment_code='this-is-a-long-owner-code',
        iphone_pwa_allow_insecure=False,
    )))
    client = TestClient(app, base_url='https://testserver')
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    response = client.post('/iphone/api/voice/turn', json={'transcript': 'hello'})
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'model_unavailable'
    assert '127.0.0.1' not in response.text


def test_model_timeout_is_not_reported_as_http_500(tmp_path):
    client, runtime = make_client(tmp_path)

    class TimeoutExecutor:
        def chat(self, *args, **kwargs):
            raise ModelTimeout('timed out', provider='self_hosted')

    runtime['executor'] = TimeoutExecutor()
    app = FastAPI()
    app.include_router(iphone_pwa_router(runtime, SimpleNamespace(
        base_dir=Path(__file__).resolve().parent.parent,
        iphone_owner_enrollment_code='this-is-a-long-owner-code',
        iphone_pwa_allow_insecure=False,
    )))
    client = TestClient(app, base_url='https://testserver')
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    response = client.post('/iphone/api/voice/turn', json={'transcript': 'hello'})
    assert response.status_code == 504
    assert response.json()['detail']['code'] == 'model_timeout'


def test_plain_http_enrollment_fails_closed(tmp_path):
    settings = SimpleNamespace(
        base_dir=Path(__file__).resolve().parent.parent,
        iphone_owner_enrollment_code='this-is-a-long-owner-code',
        iphone_pwa_allow_insecure=False,
    )
    events = EventBus()
    runtime = {
        'device_registry': Registry(),
        'executor': Executor(),
        'events': events,
        'continuity': ContinuityService(tmp_path / 'continuity.sqlite3', events=events),
        'voice_qualification': Recorder(),
        'owner_access': OwnerAccessStore(tmp_path / 'owner-access.sqlite3'),
    }
    app = FastAPI(); app.include_router(iphone_pwa_router(runtime, settings))
    client = TestClient(app, base_url='http://testserver')
    response = client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    assert response.status_code == 400


def test_conversation_survives_reload_and_continues_across_trusted_browsers(tmp_path):
    first, runtime = make_client(tmp_path)
    second = TestClient(first.app, base_url='https://testserver')
    first.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code', 'name': 'Safari'})
    second.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code', 'name': 'Installed PWA'})

    initial = first.post('/iphone/api/voice/turn', json={'transcript': 'Plan my kitchen project'})
    conversation_id = initial.json()['conversation_id']
    reloaded = first.get('/iphone/api/status').json()['conversation']
    assert reloaded['thread']['id'] == conversation_id
    assert [event['payload']['text'] for event in reloaded['events']] == [
        'Plan my kitchen project',
        'reply:Plan my kitchen project:iphone-1',
    ]

    shared = second.post(
        f'/iphone/api/conversations/{conversation_id}/activate',
        json={},
    )
    assert shared.status_code == 200
    continued = second.post('/iphone/api/voice/turn', json={
        'transcript': 'Continue with the budget',
        'conversation_id': conversation_id,
    })
    assert continued.status_code == 200

    final = first.get(f'/iphone/api/conversations/{conversation_id}').json()
    assert [event['device_id'] for event in final['events']] == [
        'iphone-1', 'iphone-1', 'iphone-2', 'iphone-2',
    ]
    assert final['events'][-1]['payload']['text'] == 'reply:Continue with the budget:iphone-2'


def test_conversation_history_can_be_created_listed_and_searched(tmp_path):
    client, _ = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    created = client.post('/iphone/api/conversations', json={'title': 'Renovation notes'}).json()
    conversation_id = created['conversation']['id']
    client.post('/iphone/api/voice/turn', json={
        'transcript': 'Compare flooring options',
        'conversation_id': conversation_id,
    })

    found = client.get('/iphone/api/conversations?q=flooring').json()
    assert [item['id'] for item in found['conversations']] == [conversation_id]
    renamed = client.patch(
        f'/iphone/api/conversations/{conversation_id}',
        json={'title': 'Home renovation'},
    )
    assert renamed.status_code == 200
    assert renamed.json()['conversation']['title'] == 'Home renovation'


def test_normal_chat_is_not_blocked_by_other_browser_qualification(tmp_path):
    first, runtime = make_client(tmp_path)
    second = TestClient(first.app, base_url='https://testserver')
    first.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    second.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    assert first.post('/iphone/api/qualification/start', json={'environment': {}}).status_code == 200

    response = second.post('/iphone/api/voice/turn', json={'transcript': 'hello from browser two'})

    assert response.status_code == 200
    assert response.json()['reply'] == 'reply:hello from browser two:iphone-2'
    assert runtime['voice_qualification'].active_session()['environment']['device_id'] == 'iphone-1'


def test_normal_chat_does_not_automatically_start_qualification(tmp_path):
    client, runtime = make_client(tmp_path)
    client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})

    assert client.post('/iphone/api/voice/turn', json={'transcript': 'normal chat'}).status_code == 200
    assert runtime['voice_qualification'].active_session() is None


def test_pwa_home_is_conversation_first_and_qualification_lives_in_advanced(tmp_path):
    client, _ = make_client(tmp_path)
    page = client.get('/iphone/').text

    assert 'id="messageStream"' in page
    assert 'id="attachmentButton"' in page
    assert 'data-module="more"' in page
    assert 'data-owner-module="settings"' in page
    assert 'Models &amp; Intelligence' in page
    assert "renderSettings('advanced')" in page
    assert '<details class="session-details">' not in page
    assert 'id="startSession"' not in page
    assert 'id="stopSession"' not in page
    assert 'Continue with Face ID' in page
    assert 'Use owner password' in page
    assert 'Having trouble?' in page
    assert 'Use enrollment code' in page
    assert 'Trust this iPhone' not in page
    assert 'localStorage' not in page
    assert 'sessionStorage' not in page


def test_browser_cannot_stop_another_browsers_qualification_session(tmp_path):
    first, runtime = make_client(tmp_path)
    second = TestClient(first.app, base_url='https://testserver')
    first.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    second.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    first.post('/iphone/api/qualification/start', json={'environment': {}})

    blocked = second.post('/iphone/api/qualification/stop', json={})

    assert blocked.status_code == 409
    assert blocked.json()['detail']['code'] == 'qualification_session_owned_by_other_device'
    assert runtime['voice_qualification'].active_session() is not None


def test_stage8_stale_server_reauth_blocks_owner_credential_changes(tmp_path):
    client, runtime = make_client(tmp_path, server_sessions=True)
    enrolled = client.post('/iphone/api/enroll', json={'code': 'this-is-a-long-owner-code'})
    assert enrolled.status_code == 200

    session_id = next(iter(runtime['pwa_sessions'].active_for_device(enrolled.json()['device_id']))).id
    assert runtime['pwa_sessions'].mark_reauthenticated(session_id, at=time.time() - 1000)

    password = client.post('/iphone/api/access/password/setup', json={
        'password': 'correct horse battery staple',
    })
    assert password.status_code == 401
    assert password.json()['detail']['code'] == 'reauthentication_required'

    recovery = client.post('/iphone/api/access/recovery/regenerate', json={})
    assert recovery.status_code == 401

    passkey = client.post('/iphone/api/access/passkey/register/options', json={})
    assert passkey.status_code == 401

    assert runtime['owner_access'].password_configured() is False
    assert runtime['owner_access'].recovery_codes_remaining() == 0


def test_stage8_rotating_forwarded_addresses_cannot_bypass_global_access_limit(tmp_path):
    client, _ = make_client(tmp_path)
    for index in range(25):
        response = client.post(
            '/iphone/api/enroll',
            json={'code': 'wrong'},
            headers={'x-forwarded-for': f'198.51.100.{index + 1}'},
        )
        assert response.status_code == 401

    blocked = client.post(
        '/iphone/api/enroll',
        json={'code': 'wrong'},
        headers={'x-forwarded-for': '203.0.113.250'},
    )
    assert blocked.status_code == 429
