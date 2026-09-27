from __future__ import annotations
from pathlib import Path
from cloud_runtime.security import CloudSessionStore,OwnerAuthenticator
from cloud_runtime.relay import SecureCloudRelay

class FakeMemory:
    def __init__(self):self.audit_rows=[];self.rows=[{'id':'1','type':'fact','subject':'normal','content':'ok','source':'user','confidence':1.0,'verified':1,'sensitivity':'normal','created_at':'x','updated_at':'x'},{'id':'2','type':'secret','subject':'private','content':'hidden','source':'user','confidence':1.0,'verified':1,'sensitivity':'private','created_at':'x','updated_at':'x'}]
    def audit(self,*args):self.audit_rows.append(args)
    def search(self,q,limit=20):return list(self.rows)
class FakeDevices:
    def __init__(self):self.active=True
    def authenticate(self,device_id,token):return self.active and device_id=='dev1' and token=='device-secret'
    def is_active(self,device_id):return self.active and device_id=='dev1'
class FakeExecutor:
    def chat(self,text):return 'reply:'+text
    def approve(self,approval_id):return 'approved'
    def reject(self,approval_id):return 'rejected'
class FakeEvents:
    def subscribe(self,*args):return lambda:None
    def emit(self,*args,**kwargs):pass

def relay(tmp_path):
    sessions=CloudSessionStore(tmp_path/'sessions.sqlite3',ttl_seconds=60);devices=FakeDevices()
    return SecureCloudRelay(executor=FakeExecutor(),memory=FakeMemory(),second_brain=None,device_registry=devices,sessions=sessions,owner=OwnerAuthenticator('x'*40),events=FakeEvents())

def test_session_is_opaque_hashed_and_revocable(tmp_path):
    store=CloudSessionStore(tmp_path/'s.sqlite3',ttl_seconds=60);token,s=store.issue('dev1')
    assert token not in (tmp_path/'s.sqlite3').read_bytes().decode('latin1',errors='ignore')
    assert store.authenticate(token,'ai:chat').device_id=='dev1'
    assert store.revoke(s.id)
    assert store.authenticate(token) is None

def test_nonce_replay_is_rejected(tmp_path):
    store=CloudSessionStore(tmp_path/'s.sqlite3',ttl_seconds=60);token,s=store.issue('dev1')
    nonce='0123456789abcdef0123456789abcdef'
    assert store.accept_nonce(s.id,nonce)
    assert not store.accept_nonce(s.id,nonce)

def test_owner_auth_requires_long_secret_and_constant_api(tmp_path):
    assert not OwnerAuthenticator('short').configured
    owner=OwnerAuthenticator('a'*32);assert owner.configured;assert owner.verify('a'*32);assert not owner.verify('b'*32)

def test_device_auth_issues_short_session(tmp_path):
    r=relay(tmp_path);bad=r.issue_session('dev1','wrong');assert bad.status==401
    good=r.issue_session('dev1','device-secret');assert good.status==200
    assert 'device-secret' not in str(good.payload)
    assert r.sessions.authenticate(good.payload['session_token'],'ai:chat')

def test_revoked_device_invalidates_existing_cloud_session(tmp_path):
    r=relay(tmp_path);issued=r.issue_session('dev1','device-secret');token=issued.payload['session_token'];r.device_registry.active=False
    error,session=r.authenticate(token,'status:read')
    assert session is None and error.status==401 and error.payload['error']=='device_revoked'
    assert r.sessions.authenticate(token) is None

def test_memory_scope_filters_sensitive_rows(tmp_path):
    r=relay(tmp_path);issued=r.issue_session('dev1','device-secret');s=r.sessions.authenticate(issued.payload['session_token'],'memory:read')
    result=r.memory_search(s,'',include_sensitive=True);assert result.status==200
    assert [x['id'] for x in result.payload['results']]==['1']

def test_emergency_stop_blocks_commands_and_approvals(tmp_path):
    r=relay(tmp_path);issued=r.issue_session('dev1','device-secret');s=r.sessions.authenticate(issued.payload['session_token'],'ai:chat')
    assert r.set_emergency_stop('x'*40,True).status==200
    assert r.command(s,'hello','0123456789abcdef').status==423
    assert r.approval(s,'a','approve').status==423
    assert r.set_emergency_stop('bad',False).status==401
    assert r.set_emergency_stop('x'*40,False).payload['emergency_stop'] is False

def test_event_bus_unsubscribe_stops_delivery():
    from core.events import EventBus
    bus=EventBus();seen=[];unsubscribe=bus.subscribe('state',seen.append);bus.emit('state',state='thinking');unsubscribe();bus.emit('state',state='idle')
    assert len(seen)==1 and seen[0]['state']=='thinking'

def test_web_companion_never_embeds_privileged_secret():
    root=Path(__file__).resolve().parents[1];text=(root/'web-companion'/'app.js').read_text()+(root/'web-companion'/'index.html').read_text()
    forbidden=['OPENAI_API_KEY','PERSONAL_AI_CLOUD_OWNER_SECRET','device-secret','APPLE_TEAM_ID','PRIVATE_KEY_B64']
    assert all(x not in text for x in forbidden)
    assert 'sessionStorage' in text
    assert 'localStorage' not in text
    assert '/cloud/command' in text and '/cloud/memory/search' in text and '/cloud/emergency-stop' in text and '/cloud/events' in text

def test_cloud_runtime_defaults_fail_closed():
    from core.config import Settings
    s=Settings();assert s.cloud_runtime_enabled is False
