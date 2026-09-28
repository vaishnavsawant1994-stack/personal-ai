import time
import pytest, requests
from integrations.contracts import gmail_manifest
from integrations.adapters import SlackAdapter,HomeAssistantAdapter
from security.request_context import TrustedRequestContext,set_trusted_request,reset_trusted_request
from tools.integrations import register as register_integration_tools
from tools.registry import ToolRegistry
from types import SimpleNamespace
from integrations.gateway import ConnectorGateway,ConnectorError,ConnectorRecoveryRequired
from integrations.state import ConnectorStateStore
class Vault:
 def __init__(self):self.d={}
 def set(self,k,v):self.d[k]=v
 def get(self,k,d=None):return self.d.get(k,d)
 def delete(self,k):self.d.pop(k,None)
class R:
 def __init__(self,status=200,data=None,headers=None,content=True):self.status_code=status;self._data={} if data is None else data;self.headers=headers or {};self.content=b'x' if content else b''
 def json(self):
  if isinstance(self._data,Exception):raise self._data
  return self._data
class Session:
 def __init__(self,seq):self.seq=list(seq);self.calls=0
 def request(self,*a,**k):
  self.calls+=1;x=self.seq.pop(0)
  if isinstance(x,Exception):raise x
  return x
class A:base_url='https://provider.test'
@pytest.fixture
def store(tmp_path):return ConnectorStateStore(tmp_path/'c.sqlite3',vault=Vault())
def test_401_maps_safe(store):
 g=ConnectorGateway(store,session=Session([R(401)]),sleep=lambda x:None)
 with pytest.raises(ConnectorError) as e:g.request(A(),gmail_manifest().operation('gmail.read'),'GET','x')
 assert e.value.code=='authentication_required'
def test_403_scope_maps_safe(store):
 g=ConnectorGateway(store,session=Session([R(403)]),sleep=lambda x:None)
 with pytest.raises(ConnectorError) as e:g.request(A(),gmail_manifest().operation('gmail.read'),'GET','x')
 assert e.value.health_state=='insufficient_scope'
def test_429_honors_retry_after(store):
 s=Session([R(429,headers={'Retry-After':'0'}),R(200,{'ok':1})]);g=ConnectorGateway(store,session=s,sleep=lambda x:None,random_fn=lambda:0.5);assert g.request(A(),gmail_manifest().operation('gmail.read'),'GET','x')['ok']==1 and s.calls==2
def test_transient_5xx_retries_read(store):
 s=Session([R(503),R(200,{'ok':1})]);g=ConnectorGateway(store,session=s,sleep=lambda x:None);assert g.request(A(),gmail_manifest().operation('gmail.read'),'GET','x')['ok']==1
def test_timeout_read_retries(store):
 s=Session([requests.Timeout(),R(200,{'ok':1})]);g=ConnectorGateway(store,session=s,sleep=lambda x:None);assert g.request(A(),gmail_manifest().operation('gmail.read'),'GET','x')['ok']==1
def test_timeout_nonidempotent_consequential_requires_recovery(store):
 s=Session([requests.Timeout(),R(200,{'id':'x'})]);g=ConnectorGateway(store,session=s,sleep=lambda x:None)
 with pytest.raises(ConnectorRecoveryRequired):g.request(A(),gmail_manifest().operation('gmail.send'),'POST','x',parameters={'to':'a@b.com'})
 assert s.calls==1
def test_malformed_response_safe(store):
 g=ConnectorGateway(store,session=Session([R(200,ValueError('bad'))]),sleep=lambda x:None)
 with pytest.raises(ConnectorError) as e:g.request(A(),gmail_manifest().operation('gmail.read'),'GET','x')
 assert e.value.code=='invalid_response'
def test_cancellation_before_dispatch(store):
 s=Session([R(200)]);g=ConnectorGateway(store,session=s)
 with pytest.raises(ConnectorError) as e:g.request(A(),gmail_manifest().operation('gmail.read'),'GET','x',cancelled=lambda:True)
 assert e.value.code=='cancelled' and s.calls==0
def test_deadline_before_dispatch(store):
 s=Session([R(200)]);g=ConnectorGateway(store,session=s)
 with pytest.raises(ConnectorError) as e:g.request(A(),gmail_manifest().operation('gmail.read'),'GET','x',deadline=time.time()-1)
 assert e.value.code=='deadline_exceeded'
def test_duplicate_consequential_dispatch_prevented(store):
 s=Session([R(200,{'id':'m1'})]);g=ConnectorGateway(store,session=s);op=gmail_manifest().operation('gmail.send');assert g.request(A(),op,'POST','x',parameters={'to':'a'},idempotency_key='k')['id']=='m1'
 before=s.calls
 with pytest.raises(ConnectorRecoveryRequired):g.request(A(),op,'POST','x',parameters={'to':'a'},idempotency_key='k')
 assert s.calls==before
def test_bounded_pagination(store):
 g=ConnectorGateway(store);op=gmail_manifest().operation('gmail.read');calls=[]
 def f(cur):calls.append(cur);return {'messages':[{'id':len(calls)}],'nextPageToken':str(len(calls)) if len(calls)<3 else None}
 r=g.paginate(f,op);assert len(r['items'])==3 and r['pages']==3
def test_cursor_cycle_detection(store):
 g=ConnectorGateway(store);op=gmail_manifest().operation('gmail.read')
 def f(cur):return {'messages':[],'nextPageToken':'same'}
 with pytest.raises(ConnectorError) as e:g.paginate(f,op)
 assert e.value.code=='cursor_cycle'


def test_stage8_slack_send_uses_connector_ledger_and_verification(store, tmp_path):
    session=Session([R(200,{'ok':True,'ts':'123.456','channel':'C1'})])
    gateway=ConnectorGateway(store,session=session,sleep=lambda x:None)
    slack=SlackAdapter('token',gateway=gateway)
    registry=ToolRegistry(SimpleNamespace(autonomy_mode='act',data_dir=tmp_path))
    register_integration_tools(registry,{'slack':slack})
    tool=registry.get('slack_send_message')
    ctx=set_trusted_request(TrustedRequestContext('device-1','session-1'))
    try:
        result=tool.handler({'channel':'C1','text':'hello'})
        verification=registry.verify_result(tool,{'channel':'C1','text':'hello'},result)
    finally:
        reset_trusted_request(ctx)

    assert session.calls==1
    assert verification.verified is True
    opid=result['_personal_ai_operation_id']
    operation=store.operation(opid)
    assert operation['owner_id']=='owner'
    assert operation['device_id']=='device-1'
    assert operation['session_id']=='session-1'
    assert operation['operation_name']=='slack.send'
    assert operation['state']=='verified'
    assert 'hello' not in repr(operation)


def test_stage8_home_assistant_service_uses_ledger_and_fresh_state_verification(store, tmp_path):
    session=Session([
        R(200,[{'entity_id':'light.kitchen','state':'on'}]),
        R(200,{'entity_id':'light.kitchen','state':'on'}),
    ])
    gateway=ConnectorGateway(store,session=session,sleep=lambda x:None)
    home=HomeAssistantAdapter('https://home.example','token',gateway=gateway)
    registry=ToolRegistry(SimpleNamespace(autonomy_mode='act',data_dir=tmp_path))
    register_integration_tools(registry,{'home_assistant':home})
    tool=registry.get('home_assistant_call_service')
    params={'domain':'light','service':'turn_on','data':{'entity_id':'light.kitchen'}}
    ctx=set_trusted_request(TrustedRequestContext('device-1','session-1'))
    try:
        result=tool.handler(params)
        verification=registry.verify_result(tool,params,result)
    finally:
        reset_trusted_request(ctx)

    assert session.calls==2
    assert verification.verified is True
    assert verification.evidence['observed_state']=='on'
    opid=result['_personal_ai_operation_id']
    operation=store.operation(opid)
    assert operation['operation_name']=='home_assistant.call_service'
    assert operation['state']=='verified'


def test_stage8_home_assistant_unverifiable_service_requires_recovery(store, tmp_path):
    session=Session([R(200,[])])
    gateway=ConnectorGateway(store,session=session,sleep=lambda x:None)
    home=HomeAssistantAdapter('https://home.example','token',gateway=gateway)
    registry=ToolRegistry(SimpleNamespace(autonomy_mode='act',data_dir=tmp_path))
    register_integration_tools(registry,{'home_assistant':home})
    tool=registry.get('home_assistant_call_service')
    params={'domain':'script','service':'turn_on','data':{}}
    ctx=set_trusted_request(TrustedRequestContext('device-1','session-1'))
    try:
        result=tool.handler(params)
        with pytest.raises(RuntimeError,match='verification failed'):
            registry.verify_result(tool,params,result)
    finally:
        reset_trusted_request(ctx)

    operation=store.operation(result['_personal_ai_operation_id'])
    assert operation['state']=='recovery_review_required'
    assert operation['retry_decision']=='no_blind_retry'
