from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.logical_request_middleware import LogicalRequestMiddleware
from server.request_aware_pwa_state import RequestAwareIphonePwaState
import server.request_aware_pwa_state as request_state_module
from server.session_bound_executor import SessionBoundExecutor
import server.session_bound_executor as session_module


RID = '550e8400-e29b-41d4-a716-446655440000'


class Lower:
    def __init__(self): self.calls=[]
    def chat(self, text, **kwargs): self.calls.append((text, kwargs)); return 'durable answer'


def test_session_bound_executor_propagates_request_id_but_not_client_authority(monkeypatch):
    lower=Lower(); bridge=SessionBoundExecutor(lower, surface='iphone-pwa')
    trusted=SimpleNamespace(device_id='trusted-device',session_id='trusted-session',reauthenticated_at=123.0)
    monkeypatch.setattr(session_module, 'current_trusted_request', lambda: trusted)
    monkeypatch.setattr(session_module, 'current_logical_request_id', lambda: RID)
    assert bridge.chat('hello', device_id='trusted-device') == 'durable answer'
    _,kwargs=lower.calls[0]
    assert kwargs['request_id']==RID
    assert kwargs['owner_id']=='owner'
    assert kwargs['device_id']=='trusted-device'
    assert kwargs['session_id']=='trusted-session'
    assert kwargs['reauthenticated_at']==123.0


def test_session_bound_executor_rejects_request_identity_mismatch(monkeypatch):
    lower=Lower(); bridge=SessionBoundExecutor(lower)
    trusted=SimpleNamespace(device_id='d1',session_id='s1',reauthenticated_at=None)
    monkeypatch.setattr(session_module, 'current_trusted_request', lambda: trusted)
    monkeypatch.setattr(session_module, 'current_logical_request_id', lambda: RID)
    try: bridge.chat('hello', request_id='123e4567-e89b-42d3-a456-426614174000')
    except PermissionError: pass
    else: raise AssertionError('wire identity mismatch must fail closed')
    assert lower.calls==[]


def test_pwa_middleware_requires_client_uuid_on_turn_and_injects_adapter():
    app=FastAPI()
    app.add_middleware(LogicalRequestMiddleware)
    @app.post('/iphone/api/voice/turn')
    def turn(): return {'ok':True}
    @app.get('/iphone/')
    def home(): return __import__('fastapi').responses.HTMLResponse('<html><body>home</body></html>')
    client=TestClient(app)
    assert client.post('/iphone/api/voice/turn',json={'transcript':'hello'}).status_code==422
    assert client.post('/iphone/api/voice/turn',json={'request_id':'unsafe','transcript':'hello'}).status_code==422
    assert client.post('/iphone/api/voice/turn',json={'request_id':RID,'transcript':'hello'}).status_code==200
    page=client.get('/iphone/')
    assert page.status_code==200
    assert '<script src="/iphone/v1-runtime.js"></script>' in page.text
    adapter=client.get('/iphone/v1-runtime.js')
    assert adapter.status_code==200
    # The transport contract is semantic, not tied to one browser UUID API.
    # Native randomUUID is preferred, while the fallback must require the Web
    # Crypto CSPRNG and construct RFC-4122 UUID-v4 variant/version bits.
    assert "typeof c.randomUUID==='function'" in adapter.text
    assert "typeof c.getRandomValues!=='function'" in adapter.text
    assert 'c.getRandomValues(b)' in adapter.text
    assert 'b[6]=(b[6]&15)|64' in adapter.text
    assert 'b[8]=(b[8]&63)|128' in adapter.text
    assert 'Secure request identity is unavailable' in adapter.text
    assert 'Math.random' not in adapter.text
    assert 'Date.now()' not in adapter.text.split('const uuid=()=>{',1)[1].split('};',1)[0]
    assert 'request_id:pending.request_id' in adapter.text


def test_client_adapter_keeps_pending_request_until_terminal_result():
    text=(Path(__file__).resolve().parent.parent/'pwa'/'v1-runtime.js').read_text()
    assert "sessionStorage.setItem(PENDING_KEY" in text
    assert "samePending" in text
    assert "for(let attempt=0;attempt<2;attempt++)" in text
    assert "clearPending(pending.request_id)" in text
    assert "if(!samePending)appendMessage('user_message',clean)" in text



def test_request_aware_voice_state_supersedes_prior_turn_cooperatively_without_claiming_durable_authority(monkeypatch):
    current = {'request_id': '11111111-1111-4111-8111-111111111111'}
    cancelled = []
    monkeypatch.setattr(request_state_module, 'current_logical_request_id', lambda: current['request_id'])
    state = RequestAwareIphonePwaState(cancel_turn=lambda request_id: cancelled.append(request_id))

    first = state.begin_turn('device-1')
    duplicate = state.begin_turn('device-1')
    assert duplicate is first
    assert not first.is_set()
    assert cancelled == []

    current['request_id'] = '22222222-2222-4222-8222-222222222222'
    second = state.begin_turn('device-1')

    assert first.is_set()
    assert not second.is_set()
    assert cancelled == []


def test_request_aware_voice_cancel_is_bound_to_exact_active_request(monkeypatch):
    current = {'request_id': '22222222-2222-4222-8222-222222222222'}
    cancelled = []
    monkeypatch.setattr(request_state_module, 'current_logical_request_id', lambda: current['request_id'])
    state = RequestAwareIphonePwaState(cancel_turn=lambda request_id: cancelled.append(request_id))
    active = state.begin_turn('device-1')

    assert state.cancel('device-1', request_id='11111111-1111-4111-8111-111111111111') is False
    assert not active.is_set()
    assert cancelled == []

    assert state.cancel('device-1', request_id=current['request_id']) is True
    assert active.is_set()
    assert cancelled == ['22222222-2222-4222-8222-222222222222']
