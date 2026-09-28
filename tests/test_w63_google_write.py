import hashlib,json,time
from types import SimpleNamespace
import pytest,requests
from integrations.contracts import drive_manifest,sheets_manifest
from integrations.gateway import ConnectorGateway,ConnectorError,ConnectorRecoveryRequired
from integrations.state import ConnectorStateStore
from integrations.google_write import GoogleDriveWriteAdapter,GoogleSheetsWriteAdapter
from tools.google_write import register as register_write
from tools.registry import ToolRegistry,Risk

DRIVE_RO='https://www.googleapis.com/auth/drive.readonly'; DRIVE_FILE='https://www.googleapis.com/auth/drive.file'
SHEETS_RO='https://www.googleapis.com/auth/spreadsheets.readonly'; SHEETS_RW='https://www.googleapis.com/auth/spreadsheets'
class Vault:
 def __init__(self):self.d={}
 def set(self,k,v):self.d[k]=v
 def get(self,k,d=None):return self.d.get(k,d)
 def delete(self,k):self.d.pop(k,None)
class R:
 def __init__(self,status=200,data=None,headers=None,content=None):
  self.status_code=status;self._data={} if data is None else data;self.headers=headers or {};self.content=(json.dumps(self._data).encode() if content is None else content)
 def json(self):
  if isinstance(self._data,Exception):raise self._data
  return self._data
class Session:
 def __init__(self,seq):self.seq=list(seq);self.calls=[]
 def request(self,*a,**k):
  self.calls.append((a,k));x=self.seq.pop(0)
  if isinstance(x,Exception):raise x
  return x
@pytest.fixture
def store(tmp_path):return ConnectorStateStore(tmp_path/'c.sqlite3',vault=Vault())
def gw(store,seq):return ConnectorGateway(store,session=Session(seq),sleep=lambda _:None,random_fn=lambda:0.5)

def test_write_manifests_are_granular_and_no_dangerous_ops():
 d=drive_manifest();s=sheets_manifest();d.validate();s.validate();dn={x.name for x in d.operations};sn={x.name for x in s.operations}
 assert {'drive.files.create','drive.files.upload','drive.files.rename','drive.files.update_content'}<=dn
 assert {'sheets.spreadsheets.create','sheets.values.update','sheets.values.append'}<=sn
 assert not any(x in dn for x in {'drive.files.delete','drive.files.trash','drive.files.share','drive.files.move'})
 assert not any(x in sn for x in {'sheets.values.clear','sheets.worksheets.delete','sheets.spreadsheets.delete','sheets.batchUpdate'})
 assert DRIVE_FILE in d.optional_oauth_scopes and SHEETS_RW in s.optional_oauth_scopes
 assert all(o.approval=='required' and o.requires_reauth for o in d.operations if o.effect!='read')
 assert all(o.approval=='required' and o.requires_reauth for o in s.operations if o.effect!='read')
 assert all(not o.rollback_available and not o.idempotency_supported for o in [*d.operations,*s.operations] if o.effect!='read')

def test_missing_write_scope_fails_before_dispatch(store):
 sess=Session([]);g=ConnectorGateway(store,session=sess);a=GoogleDriveWriteAdapter('t',gateway=g,granted_scopes={DRIVE_RO})
 with pytest.raises(ConnectorError) as e:a.create_file('x.txt','text/plain',provider_account='a@example.com',request_id='r1')
 assert e.value.code=='insufficient_scope' and not sess.calls

def test_drive_create_verified(store):
 meta={'id':'f1','name':'x.txt','mimeType':'text/plain','version':'1','parents':['p']};g=gw(store,[R(data=meta),R(data=meta)]);a=GoogleDriveWriteAdapter('t',gateway=g,granted_scopes={DRIVE_RO,DRIVE_FILE})
 out=a.create_file('x.txt','text/plain',parent_id='p',provider_account='a@example.com',request_id='r1');assert out['verified'] and out['id']=='f1'
 op=store.by_idempotency('drive-create:a@example.com:r1');assert op['state']=='verified' and op['provider_account']=='a@example.com'

def test_drive_upload_verified_checksum(store):
 data=b'hello';meta={'id':'f1','name':'x.txt','mimeType':'text/plain','version':'2','size':'5','md5Checksum':hashlib.md5(data).hexdigest()};g=gw(store,[R(data=meta),R(data=meta)]);a=GoogleDriveWriteAdapter('t',gateway=g,granted_scopes={DRIVE_RO,DRIVE_FILE})
 out=a.upload_file('x.txt','text/plain',data,provider_account='a@example.com',request_id='r2');assert out['verified']
 op=store.by_idempotency('drive-upload:a@example.com:r2');assert op['content_checksum']==hashlib.sha256(data).hexdigest()
 assert g.session.calls[0][1]['params']['uploadType']=='multipart' and b'hello' in g.session.calls[0][1]['data']

def test_drive_invalid_name_mime_and_size(store):
 a=GoogleDriveWriteAdapter('t',gateway=gw(store,[]),granted_scopes={DRIVE_FILE})
 for args in [('\n','text/plain','x'),('x','application/x-msdownload','x')]:
  with pytest.raises(ConnectorError):a.upload_file(args[0],args[1],args[2],provider_account='a',request_id='r')
 with pytest.raises(ConnectorError) as e:a.upload_file('x','text/plain','x'*(10*1024*1024+1),provider_account='a',request_id='r');assert e.value.code=='content_too_large'

def test_drive_rename_stale_version_conflict_no_write(store):
 before={'id':'f','name':'old','mimeType':'text/plain','version':'3'};g=gw(store,[R(data=before)]);a=GoogleDriveWriteAdapter('t',gateway=g,granted_scopes={DRIVE_RO,DRIVE_FILE})
 with pytest.raises(ConnectorError) as e:a.rename_file('f','new',expected_name='old',expected_version='2',provider_account='a',request_id='r')
 assert e.value.code=='precondition_conflict' and len(g.session.calls)==1

def test_drive_rename_verified(store):
 before={'id':'f','name':'old','mimeType':'text/plain','version':'2'};patched={'id':'f','name':'new','mimeType':'text/plain','version':'3'};after=dict(patched)
 g=gw(store,[R(data=before,headers={'ETag':'e2'}),R(data=patched),R(data=after)]);a=GoogleDriveWriteAdapter('t',gateway=g,granted_scopes={DRIVE_RO,DRIVE_FILE});out=a.rename_file('f','new',expected_name='old',expected_version='2',provider_account='a',request_id='r');assert out['verified'] and g.session.calls[1][1]['headers']['If-Match']=='e2'

def test_drive_update_content_verified(store):
 data=b'new';before={'id':'f','name':'x','mimeType':'text/plain','version':'2','size':'3'};patched={'id':'f','version':'3'};after={'id':'f','name':'x','mimeType':'text/plain','version':'3','size':'3','md5Checksum':hashlib.md5(data).hexdigest()}
 g=gw(store,[R(data=before),R(data=patched),R(data=after)]);a=GoogleDriveWriteAdapter('t',gateway=g,granted_scopes={DRIVE_RO,DRIVE_FILE});out=a.update_content('f','text/plain',data,expected_version='2',provider_account='a',request_id='r');assert out['verified']

def test_uncertain_drive_timeout_no_redispatch(store):
 g=gw(store,[requests.Timeout()]);a=GoogleDriveWriteAdapter('t',gateway=g,granted_scopes={DRIVE_FILE})
 with pytest.raises(ConnectorRecoveryRequired):a.create_file('x.txt','text/plain',provider_account='a',request_id='same')
 assert len(g.session.calls)==1 and store.by_idempotency('drive-create:a:same')['state']=='recovery_review_required'
 with pytest.raises(ConnectorRecoveryRequired):a.create_file('x.txt','text/plain',provider_account='a',request_id='same')
 assert len(g.session.calls)==1

def test_idempotency_key_parameter_conflict(store):
 g=gw(store,[R(data={'id':'f','name':'x','mimeType':'text/plain','version':'1'}),R(data={'id':'f','name':'x','mimeType':'text/plain','version':'1'})]);a=GoogleDriveWriteAdapter('t',gateway=g,granted_scopes={DRIVE_FILE,DRIVE_RO});a.create_file('x','text/plain',provider_account='a',request_id='r')
 with pytest.raises(ConnectorError) as e:a.create_file('y','text/plain',provider_account='a',request_id='r')
 assert e.value.code=='idempotency_conflict'

def test_sheets_create_verified(store):
 created={'spreadsheetId':'s1'};meta={'spreadsheetId':'s1','properties':{'title':'T'},'sheets':[]};g=gw(store,[R(data=created),R(data=meta)]);a=GoogleSheetsWriteAdapter('t',gateway=g,granted_scopes={SHEETS_RO,SHEETS_RW});out=a.create_spreadsheet('T',provider_account='a',request_id='r');assert out['verified']

def vh(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def test_sheets_update_raw_literal_and_readback(store):
 old=[['old']];new=[['=SUM(A1:A2)','+x','-y','@z']];seq=[R(data={'range':'Data!A1:D1','values':old}),R(data={'updatedRange':'Data!A1:D1','updatedRows':1,'updatedColumns':4,'updatedCells':4}),R(data={'range':'Data!A1:D1','values':new})];g=gw(store,seq);a=GoogleSheetsWriteAdapter('t',gateway=g,granted_scopes={SHEETS_RO,SHEETS_RW});out=a.update_values('s','Data!A1:D1',new,provider_account='a',request_id='r',expected_current_hash=vh(old));assert out['verified'];call=g.session.calls[1][1];assert call['params']['valueInputOption']=='RAW' and call['json']['values'][0][0].startswith('=')

def test_sheets_update_detects_concurrent_change(store):
 old=[['other']];g=gw(store,[R(data={'range':'A1:A1','values':old})]);a=GoogleSheetsWriteAdapter('t',gateway=g,granted_scopes={SHEETS_RO,SHEETS_RW})
 with pytest.raises(ConnectorError) as e:a.update_values('s','A1:A1',[['x']],provider_account='a',request_id='r',expected_current_hash=vh([['expected']]))
 assert e.value.code=='precondition_conflict' and len(g.session.calls)==1

def test_sheets_append_verified_and_no_auto_rollback(store):
 vals=[['x','y']];resp={'updates':{'updatedRange':'Data!A5:B5'}};g=gw(store,[R(data=resp),R(data={'range':'Data!A5:B5','values':vals})]);a=GoogleSheetsWriteAdapter('t',gateway=g,granted_scopes={SHEETS_RO,SHEETS_RW});out=a.append_values('s','Data!A1:B100',vals,provider_account='a',request_id='r');assert out['verified'] and out['verification']['rollback_available'] is False

def test_sheets_append_uncertain_timeout_no_blind_retry(store):
 g=gw(store,[requests.Timeout()]);a=GoogleSheetsWriteAdapter('t',gateway=g,granted_scopes={SHEETS_RW})
 with pytest.raises(ConnectorRecoveryRequired):a.append_values('s','A1:B10',[['x','y']],provider_account='a',request_id='r')
 assert len(g.session.calls)==1 and store.by_idempotency('sheets-append:a:r')['state']=='recovery_review_required'

def test_sheets_limits(store):
 a=GoogleSheetsWriteAdapter('t',gateway=gw(store,[]),granted_scopes={SHEETS_RW})
 with pytest.raises(ConnectorError):a.append_values('s','A1:A1000',[['x']]*501,provider_account='a',request_id='r')

def test_tools_require_approval_reauth_and_no_rollback(tmp_path):
 class D:
  gateway=None
  create_file=upload_file=rename_file=update_content=lambda *a,**k:{'verified':True,'verification':{}}
 class S:
  gateway=None
  create_spreadsheet=update_values=append_values=lambda *a,**k:{'verified':True,'verification':{}}
 r=ToolRegistry(SimpleNamespace(autonomy_mode='act',data_dir=tmp_path));register_write(r,{'drive':D(),'sheets':S()});writes=[t for t in r.all() if t.connector_id in {'drive','sheets'}]
 assert len(writes)==7 and all(t.requires_reauth and t.risk==Risk.EXTERNAL_SIDE_EFFECT and t.verification_required and not callable(t.rollback) for t in writes)
 assert all(not r.authorize(t,parameters={'file_id':'f'}).allowed for t in writes)
 r.set_emergency_stop(True);assert all(not r.authorize(t).allowed for t in writes)

def test_destination_binds_sheet_range_and_drive_resource():
 assert ToolRegistry.destination({'spreadsheet_id':'s','range':'Data!A1:B2'})=='s#Data!A1:B2'
 assert ToolRegistry.destination({'file_id':'f','new_name':'x'})=='file:f'
 assert ToolRegistry.destination({'parent_id':'p','filename':'x'})=='parent:p/name:x'

def test_operation_migration_adds_w63_fields(tmp_path):
 import sqlite3
 p=tmp_path/'c.sqlite3';c=sqlite3.connect(p);c.executescript("CREATE TABLE connector_health(connector_id TEXT PRIMARY KEY,state TEXT NOT NULL DEFAULT 'disconnected',granted_scopes_json TEXT NOT NULL DEFAULT '[]',last_success_at REAL,last_checked_at REAL,last_error_code TEXT,last_error_message TEXT,revocation_status TEXT NOT NULL DEFAULT 'none',updated_at REAL NOT NULL); CREATE TABLE oauth_transactions(state_digest TEXT PRIMARY KEY,owner_id TEXT NOT NULL,device_id TEXT,session_id TEXT,connector_id TEXT NOT NULL,provider_id TEXT NOT NULL,scopes_json TEXT NOT NULL,challenge TEXT NOT NULL,nonce_digest TEXT,redirect_uri TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL,consumed_at REAL,security_epoch INTEGER NOT NULL,relink_intent TEXT NOT NULL DEFAULT 'connect',status TEXT NOT NULL DEFAULT 'pending',failure_code TEXT); CREATE TABLE connector_operations(operation_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,device_id TEXT,session_id TEXT,connector_id TEXT NOT NULL,operation_name TEXT NOT NULL,parameter_hash TEXT NOT NULL,destination TEXT NOT NULL DEFAULT '',idempotency_key TEXT NOT NULL UNIQUE,provider_request_id TEXT,provider_resource_id TEXT,dispatch_time REAL,state TEXT NOT NULL,verification_state TEXT NOT NULL DEFAULT 'not_started',rollback_available INTEGER NOT NULL DEFAULT 0,retry_decision TEXT NOT NULL DEFAULT '',result_json TEXT NOT NULL DEFAULT '{}',created_at REAL NOT NULL,updated_at REAL NOT NULL);");c.commit();c.close();s=ConnectorStateStore(p,vault=Vault());cols={r['name'] for r in s._con().execute('PRAGMA table_info(connector_operations)')};assert {'provider_account','content_checksum','verification_evidence_json'}<=cols
