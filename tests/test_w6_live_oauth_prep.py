from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from integrations.state import ConnectorStateStore
from integrations.oauth import OAuthAccountManager,OAuthProvider
from integrations.oauth_callback import resolve_oauth_context
from integrations.registry import IntegrationRegistry,Integration
from integrations.contracts import drive_manifest
from security.request_context import TrustedRequestContext,set_trusted_request,reset_trusted_request
from server.connector_api import connector_router
from server.connector_oauth_callback import connector_oauth_callback_router
from qualification.google_connectors import GoogleQualificationEvidence,GoogleQualificationRecorder,qualification_resource_names

class Vault:
    def __init__(self):self.d={}
    def set(self,k,v):self.d[k]=v
    def get(self,k,d=None):return self.d.get(k,d)
    def delete(self,k):self.d.pop(k,None)
class Devices:
    def authenticate(self,d,t):return d=='d' and t=='t'
    def authorize(self,d,s):return True
class CtxMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        tok=set_trusted_request(TrustedRequestContext('d','s'))
        try:return await call_next(request)
        finally:reset_trusted_request(tok)

def env(tmp_path):
    v=Vault();st=ConnectorStateStore(tmp_path/'c.sqlite3',vault=v);provider=OAuthProvider('google','https://accounts.google.com/o/oauth2/v2/auth','https://oauth2.googleapis.com/token','cid',['scope'],'secret');oauth=OAuthAccountManager(v,redirect_uri='https://q.example/connector-oauth/callback',state_store=st,allowed_redirects={'https://q.example/connector-oauth/callback'},security_epoch_provider=lambda:3)
    reg=IntegrationRegistry(state_store=st);m=drive_manifest();reg.register_manifest(m);reg.register(Integration('drive','Google Drive',set(),None,m,True))
    runtime={'device_registry':Devices(),'integrations':reg,'oauth':oauth,'oauth_providers':{'google':provider},'integration_adapters':{},'executor':SimpleNamespace(approvals=SimpleNamespace(current_security_epoch=lambda:3))}
    return v,st,provider,oauth,runtime

def test_context_resolves_route_without_consuming(tmp_path):
    v,st,p,o,r=env(tmp_path);x=o.begin(p,owner_id='owner',device_id='d',session_id='s',connector_id='drive',scopes=['scope'],security_epoch=3)
    c=resolve_oauth_context(st,state=x['state'],owner_id='owner',device_id='d',session_id='s',security_epoch=3)
    assert c['connector_id']=='drive' and c['provider_id']=='google'
    with st._con() as db: assert db.execute('select status from oauth_transactions').fetchone()['status']=='pending'

def test_context_wrong_session_and_expiry_fail(tmp_path):
    v,st,p,o,r=env(tmp_path);x=o.begin(p,owner_id='owner',device_id='d',session_id='s',connector_id='drive',scopes=['scope'],security_epoch=3)
    with pytest.raises(PermissionError):resolve_oauth_context(st,state=x['state'],owner_id='owner',device_id='d',session_id='wrong',security_epoch=3)
    with pytest.raises(PermissionError):resolve_oauth_context(st,state=x['state'],owner_id='owner',device_id='d',session_id='s',security_epoch=3,now=10**12)

def test_public_callback_shell_contains_no_provider_secrets():
    app=FastAPI();app.include_router(connector_oauth_callback_router());c=TestClient(app);r=c.get('/connector-oauth/callback?state=state-secret&code=code-secret')
    assert r.status_code==200 and 'state-secret' not in r.text and 'code-secret' not in r.text and 'oauth/finalize' in r.text
    assert r.headers['cache-control']=='no-store' and r.headers['referrer-policy']=='no-referrer'

def test_generic_finalize_is_bound_to_durable_state(tmp_path,monkeypatch):
    v,st,p,o,runtime=env(tmp_path);x=o.begin(p,owner_id='owner',device_id='d',session_id='s',connector_id='drive',scopes=['scope'],security_epoch=3)
    class Resp:
        def raise_for_status(self):pass
        def json(self):return {'access_token':'secret-token','scope':'scope','refresh_token':'secret-refresh'}
    monkeypatch.setattr('integrations.oauth.requests.post',lambda *a,**k:Resp())
    app=FastAPI();app.add_middleware(CtxMiddleware);app.include_router(connector_router(runtime));c=TestClient(app)
    res=c.post('/iphone/api/connectors/oauth/finalize',json={'state':x['state'],'code':'provider-code'},cookies={'pa_device':'d','pa_token':'t'})
    assert res.status_code==200 and res.json()['connected'] is True
    assert 'secret-token' not in res.text and 'provider-code' not in res.text
    again=c.post('/iphone/api/connectors/oauth/finalize',json={'state':x['state'],'code':'again'},cookies={'pa_device':'d','pa_token':'t'});assert again.status_code==403

def test_callback_redirect_is_explicit_https(tmp_path):
    v,st,p,o,r=env(tmp_path);x=o.begin(p,owner_id='owner',device_id='d',session_id='s',connector_id='drive',scopes=['scope'],security_epoch=3)
    assert 'redirect_uri=https%3A%2F%2Fq.example%2Fconnector-oauth%2Fcallback' in x['url']

def test_qualification_evidence_redacts_and_harmless_names(tmp_path):
    rec=GoogleQualificationRecorder(tmp_path/'evidence.jsonl');row=rec.append(GoogleQualificationEvidence('sha','dep','qualification','svc','person@example.com','drive',['b','a'],'owner','d','s',3,'op','created','created',1.0,{'status':200,'access_token':'DO-NOT-STORE','message':'ok'},'artifact:1',True))
    raw=(tmp_path/'evidence.jsonl').read_text();assert 'person@example.com' not in raw and 'DO-NOT-STORE' not in raw and row['google_account'].endswith('@example.com')
    names=qualification_resource_names(123);assert all('Personal AI Connector Qualification 123' in x for x in names.values())
