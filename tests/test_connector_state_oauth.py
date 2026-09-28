import json,threading,time
import pytest
from integrations.state import ConnectorStateStore
from integrations.oauth import OAuthAccountManager,OAuthProvider
class Vault:
    def __init__(self):self.d={}
    def set(self,k,v):self.d[k]=v
    def get(self,k,d=None):return self.d.get(k,d)
    def delete(self,k):self.d.pop(k,None)
@pytest.fixture
def env(tmp_path):
    v=Vault();s=ConnectorStateStore(tmp_path/'connectors.sqlite3',vault=v);return v,s

def create(s,v,**kw):
    base=dict(state='state-0123456789-abcdef',verifier='verify-secret',owner_id='owner',device_id='d1',session_id='s1',connector_id='gmail',provider_id='google',scopes=['scope'],challenge='challenge',nonce='nonce',redirect_uri='https://app.example/callback',security_epoch=4)
    base.update(kw);s.create_oauth(**base);return base['state']
def test_oauth_survives_restart(env,tmp_path):
    v,s=env;state=create(s,v);s2=ConnectorStateStore(tmp_path/'connectors.sqlite3',vault=v);row=s2.consume_oauth(state=state,owner_id='owner',device_id='d1',session_id='s1',connector_id='gmail',provider_id='google',security_epoch=4);assert row['verifier']=='verify-secret'
def test_single_use_and_replay_rejected(env):
    v,s=env;state=create(s,v);s.consume_oauth(state=state,owner_id='owner',device_id='d1',session_id='s1',connector_id='gmail',provider_id='google',security_epoch=4)
    with pytest.raises(PermissionError):s.consume_oauth(state=state,owner_id='owner',device_id='d1',session_id='s1',connector_id='gmail',provider_id='google',security_epoch=4)
def test_expired_state(env):
    v,s=env;state=create(s,v,ttl_seconds=60)
    with pytest.raises(PermissionError):s.consume_oauth(state=state,owner_id='owner',device_id='d1',session_id='s1',connector_id='gmail',provider_id='google',security_epoch=4,now=time.time()+61)
@pytest.mark.parametrize('field,value,msg',[('owner_id','other','owner'),('device_id','d2','device'),('session_id','s2','session'),('security_epoch',5,'security epoch')])
def test_binding_mismatches(env,field,value,msg):
    v,s=env;state=create(s,v);args=dict(state=state,owner_id='owner',device_id='d1',session_id='s1',connector_id='gmail',provider_id='google',security_epoch=4);args[field]=value
    with pytest.raises(PermissionError,match=msg):s.consume_oauth(**args)
def test_device_revocation_invalidates_pending(env):
    v,s=env;state=create(s,v);assert s.invalidate_device('d1')==1
    with pytest.raises(PermissionError):s.consume_oauth(state=state,owner_id='owner',device_id='d1',session_id='s1',connector_id='gmail',provider_id='google',security_epoch=4)
def test_session_revocation_invalidates_pending(env):
    v,s=env;state=create(s,v);assert s.invalidate_session('s1')==1
    with pytest.raises(PermissionError):s.consume_oauth(state=state,owner_id='owner',device_id='d1',session_id='s1',connector_id='gmail',provider_id='google',security_epoch=4)
def test_concurrent_callback_consumption_only_one_wins(env):
    v,s=env;state=create(s,v);out=[]
    def f():
        try:s.consume_oauth(state=state,owner_id='owner',device_id='d1',session_id='s1',connector_id='gmail',provider_id='google',security_epoch=4);out.append('ok')
        except Exception:out.append('no')
    a=threading.Thread(target=f);b=threading.Thread(target=f);a.start();b.start();a.join();b.join();assert out.count('ok')==1

def test_state_digest_only_and_verifier_in_vault(env):
    v,s=env;state=create(s,v)
    with s._con() as c:raw=json.dumps([dict(r) for r in c.execute('SELECT * FROM oauth_transactions')])
    assert state not in raw and 'verify-secret' not in raw;assert any(k.startswith('oauth-txn:') for k in v.d)
def test_audit_redacts_secrets(env):
    v,s=env;s.audit('x',connector_id='gmail',payload={'token':'abc','authorization_code':'xyz','safe':'ok'})
    p=json.dumps(s.lifecycle.entries()[0]['payload'])
    assert 'abc' not in p and 'xyz' not in p and 'ok' in p and s.verify_audit_chain()
def test_operation_idempotency_is_durable(env,tmp_path):
    v,s=env;a,new=s.propose_operation(connector_id='gmail',operation_name='gmail.send',parameter_hash='h',idempotency_key='same');assert new
    s2=ConnectorStateStore(tmp_path/'connectors.sqlite3',vault=v);b,new2=s2.propose_operation(connector_id='gmail',operation_name='gmail.send',parameter_hash='h',idempotency_key='same');assert not new2 and a['operation_id']==b['operation_id']
def test_operation_states_persist(env):
    v,s=env;op,_=s.propose_operation(connector_id='calendar',operation_name='calendar.create',parameter_hash='h');s.transition_operation(op['operation_id'],'dispatched');s.transition_operation(op['operation_id'],'recovery_review_required',verification_state='outcome_unknown');assert s.operation(op['operation_id'])['state']=='recovery_review_required'
def test_health_state_and_scopes(env):
    v,s=env;s.set_health('gmail','healthy',scopes=['a'],success=True);h=s.health('gmail');assert h['state']=='healthy' and h['granted_scopes']==['a'] and h['last_success_at']
def test_repeated_startup_migration(env,tmp_path):
    v,s=env;ConnectorStateStore(tmp_path/'connectors.sqlite3',vault=v);ConnectorStateStore(tmp_path/'connectors.sqlite3',vault=v)
def test_partial_health_schema_additive(tmp_path):
    import sqlite3
    p=tmp_path/'connectors.sqlite3';c=sqlite3.connect(p);c.execute("CREATE TABLE connector_health(connector_id TEXT PRIMARY KEY,state TEXT,granted_scopes_json TEXT,last_success_at REAL,last_checked_at REAL,updated_at REAL)");c.commit();c.close();s=ConnectorStateStore(p,vault=Vault());cols={r['name'] for r in s._con().execute('PRAGMA table_info(connector_health)')};assert {'revocation_status','last_error_code','last_error_message'}<=cols

def test_oauth_redirect_allowlist(env):
    v,s=env;m=OAuthAccountManager(v,state_store=s,allowed_redirects={'https://ok/cb'});p=OAuthProvider('google','https://a','https://t','id',['scope'])
    with pytest.raises(ValueError):m.begin(p,connector_id='gmail',redirect_uri='https://evil/cb')
def test_legacy_oauth_begin_still_works():
    v=Vault();m=OAuthAccountManager(v);p=OAuthProvider('x','https://a','https://t','cid',['one']);o=m.begin(p);assert o['state'] in m._pending and 'code_challenge=' in o['url']

def test_google_begin_requests_incremental_scope_preservation(env):
    import urllib.parse
    v,s=env;m=OAuthAccountManager(v,state_store=s,allowed_redirects={'https://ok/cb'});p=OAuthProvider('google','https://accounts.google.com/o/oauth2/v2/auth','https://oauth2.googleapis.com/token','id',['scope'])
    o=m.begin(p,connector_id='drive',scopes=['new.scope'],redirect_uri='https://ok/cb',owner_id='owner',device_id='d',session_id='s',security_epoch=1)
    q=urllib.parse.parse_qs(urllib.parse.urlparse(o['url']).query);assert q['include_granted_scopes']==['true'] and q['scope']==['new.scope']

def test_google_scope_union_preserved_and_reduction_detected(env,monkeypatch):
    class Resp:
        def __init__(self,scope):self.scope=scope
        def raise_for_status(self):pass
        def json(self):return {'access_token':'new','scope':self.scope,'refresh_token':'r'}
    v,s=env;p=OAuthProvider('google','https://a','https://t','id',['new'])
    v.set('oauth:google',json.dumps({'access_token':'old','granted_scopes':['gmail','calendar'],'confirmed_granted_scopes':['gmail','calendar']}))
    m=OAuthAccountManager(v,state_store=s,allowed_redirects={'https://ok/cb'})
    o=m.begin(p,connector_id='drive',scopes=['drive'],redirect_uri='https://ok/cb',owner_id='owner',device_id='d',session_id='ss',security_epoch=0)
    monkeypatch.setattr('integrations.oauth.requests.post',lambda *a,**k:Resp('gmail calendar drive'))
    r=m.complete(o['state'],'code',p,connector_id='drive',owner_id='owner',device_id='d',session_id='ss',security_epoch=0);assert set(r['confirmed_scope_union'])=={'gmail','calendar','drive'} and not r['scope_reduction_detected']
    o2=m.begin(p,connector_id='drive',scopes=['drive'],redirect_uri='https://ok/cb',owner_id='owner',device_id='d',session_id='ss',security_epoch=0)
    monkeypatch.setattr('integrations.oauth.requests.post',lambda *a,**k:Resp('drive'))
    r2=m.complete(o2['state'],'code2',p,connector_id='drive',owner_id='owner',device_id='d',session_id='ss',security_epoch=0);rec=m.token_record(p);assert r2['scope_reduction_detected'] and set(rec['confirmed_granted_scopes'])=={'gmail','calendar','drive'} and rec['granted_scopes']==['drive']
