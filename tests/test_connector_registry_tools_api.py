from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from integrations.registry import IntegrationRegistry,Integration
from integrations.contracts import gmail_manifest,calendar_manifest
from integrations.state import ConnectorStateStore
from tools.registry import ToolRegistry,Risk
from tools.integrations import register as register_tools
from server.connector_api import connector_router
from server.connector_ui import JS
from security.request_context import TrustedRequestContext,set_trusted_request,reset_trusted_request

class Vault:
    def __init__(self):self.d={}
    def set(self,k,v):self.d[k]=v
    def get(self,k,d=None):return self.d.get(k,d)
    def delete(self,k):self.d.pop(k,None)
class Gmail:
    gateway=None
    def list_messages(self,**kw):return {'messages':[]}
    def get_message(self,*a,**kw):return {'id':a[0] if a else 'm'}
    def search_messages(self,*a,**kw):return {'messages':[]}
    def send_raw(self,*a,**kw):return {'id':'m1'}
    def create_draft(self,*a,**kw):return {'id':'d1'}
    def modify_message(self,*a,**kw):return {'id':'m1'}
    def delete_message(self,*a,**kw):raise PermissionError('prohibited')
class Calendar:
    gateway=None
    def list_events(self,*a,**kw):return {'items':[]}
    def create_event(self,*a,**kw):return {'id':'e1'}
    def update_event(self,*a,**kw):return {'id':'e1'}
    def delete_event(self,*a,**kw):return {}
    def verify_event(self,*a,**kw):return False

def test_registry_lists_unconfigured_manifest(tmp_path):
    s=ConnectorStateStore(tmp_path/'c.sqlite3',vault=Vault());r=IntegrationRegistry(state_store=s);r.register_manifest(gmail_manifest());x=r.list()[0];assert x['id']=='gmail' and x['state']=='not_configured' and x['configured'] is False
def test_registry_connected_details_safe(tmp_path):
    s=ConnectorStateStore(tmp_path/'c.sqlite3',vault=Vault());r=IntegrationRegistry(state_store=s);m=gmail_manifest();r.register_manifest(m);r.register(Integration('gmail','Gmail',set(),None,m,True));s.set_health('gmail','healthy',scopes=list(m.required_oauth_scopes),success=True);x=r.list()[0];assert x['state']=='healthy' and 'access_token' not in str(x)
def test_registry_limited_scopes(tmp_path):
    s=ConnectorStateStore(tmp_path/'c.sqlite3',vault=Vault());r=IntegrationRegistry(state_store=s);m=gmail_manifest();r.register_manifest(m);r.register(Integration('gmail','Gmail',set(),None,m,True));s.set_health('gmail','healthy',scopes=['other'],success=True);assert r.list()[0]['state']=='insufficient_scope'
def test_gmail_existing_read_tool_preserved(tmp_path):
    r=ToolRegistry(SimpleNamespace(autonomy_mode='ask',data_dir=tmp_path));register_tools(r,{'gmail':Gmail()});assert r.get('gmail_list_messages').risk==Risk.READ_ONLY and r.get('gmail_list_messages').handler({})=={'messages':[]}
def test_gmail_send_governance(tmp_path):
    r=ToolRegistry(SimpleNamespace(autonomy_mode='ask',data_dir=tmp_path));register_tools(r,{'gmail':Gmail()});t=r.get('gmail_send_message');assert t.risk==Risk.EXTERNAL_SIDE_EFFECT and t.verification_required and not r.authorize(t,parameters={'to':'a@example.com'}).allowed
def test_gmail_delete_prohibited(tmp_path):
    r=ToolRegistry(SimpleNamespace(autonomy_mode='act',data_dir=tmp_path));register_tools(r,{'gmail':Gmail()});t=r.get('gmail_delete_message');assert t.prohibited and not r.authorize(t).allowed
def test_calendar_create_has_verification_and_rollback(tmp_path):
    r=ToolRegistry(SimpleNamespace(autonomy_mode='ask',data_dir=tmp_path));register_tools(r,{'calendar':Calendar()});t=r.get('calendar_create_event');assert t.verification_required and callable(t.rollback)
def test_calendar_delete_reauth(tmp_path):
    r=ToolRegistry(SimpleNamespace(autonomy_mode='ask',data_dir=tmp_path));register_tools(r,{'calendar':Calendar()});t=r.get('calendar_delete_event');assert t.requires_reauth and t.risk==Risk.DESTRUCTIVE
def test_ui_has_no_secret_fields():
    low=JS.lower();assert 'access_token' not in low and 'refresh_token' not in low and 'client_secret' not in low and 'apps &amp; tools' in low

def test_api_rejects_untrusted_browser(tmp_path):
    class Devices:
        def authenticate(self,d,t):return False
        def authorize(self,d,s):return False
    st=ConnectorStateStore(tmp_path/'c.sqlite3',vault=Vault());reg=IntegrationRegistry(state_store=st);reg.register_manifest(gmail_manifest())
    app=FastAPI();app.include_router(connector_router({'device_registry':Devices(),'integrations':reg,'oauth':None,'oauth_providers':{},'executor':SimpleNamespace(approvals=SimpleNamespace(current_security_epoch=lambda:0))}))
    c=TestClient(app);res=c.get('/iphone/api/connectors',cookies={'pa_device':'x','pa_token':'y'});assert res.status_code==401

def test_api_owner_list_safe(tmp_path):
    class Devices:
        def authenticate(self,d,t):return True
        def authorize(self,d,s):return True
    class CtxMiddleware(BaseHTTPMiddleware):
        async def dispatch(self,request,call_next):
            tok=set_trusted_request(TrustedRequestContext('d','s'))
            try:return await call_next(request)
            finally:reset_trusted_request(tok)
    st=ConnectorStateStore(tmp_path/'c.sqlite3',vault=Vault());reg=IntegrationRegistry(state_store=st);reg.register_manifest(gmail_manifest())
    app=FastAPI();app.add_middleware(CtxMiddleware);app.include_router(connector_router({'device_registry':Devices(),'integrations':reg,'oauth':None,'oauth_providers':{},'executor':SimpleNamespace(approvals=SimpleNamespace(current_security_epoch=lambda:0))}))
    c=TestClient(app);res=c.get('/iphone/api/connectors',cookies={'pa_device':'d','pa_token':'t'});assert res.status_code==200 and res.json()['connectors'][0]['id']=='gmail'

def test_api_drive_knowledge_requires_explicit_approval(tmp_path):
    class Devices:
        def authenticate(self,d,t):return True
        def authorize(self,d,s):return True
    class CtxMiddleware(BaseHTTPMiddleware):
        async def dispatch(self,request,call_next):
            tok=set_trusted_request(TrustedRequestContext('d','s'))
            try:return await call_next(request)
            finally:reset_trusted_request(tok)
    st=ConnectorStateStore(tmp_path/'c.sqlite3',vault=Vault());reg=IntegrationRegistry(state_store=st);reg.register_manifest(gmail_manifest())
    app=FastAPI();app.add_middleware(CtxMiddleware);app.include_router(connector_router({'device_registry':Devices(),'integrations':reg,'oauth':None,'oauth_providers':{},'integration_adapters':{},'knowledge':None,'executor':SimpleNamespace(approvals=SimpleNamespace(current_security_epoch=lambda:0))}))
    c=TestClient(app);res=c.post('/iphone/api/connectors/drive/files/f/knowledge',json={'approved':False},cookies={'pa_device':'d','pa_token':'t'});assert res.status_code==409
