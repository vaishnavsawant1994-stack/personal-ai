import time, pytest, requests
from integrations.google_read import GoogleDriveAdapter,GoogleSheetsAdapter,validate_a1_range,safe_cell_for_export
from integrations.contracts import drive_manifest,sheets_manifest
from integrations.gateway import ConnectorGateway,ConnectorError
from integrations.state import ConnectorStateStore

class Vault:
 def __init__(self):self.d={}
 def set(self,k,v):self.d[k]=v
 def get(self,k,d=None):return self.d.get(k,d)
 def delete(self,k):self.d.pop(k,None)
class R:
 def __init__(self,status=200,data=None,headers=None,content=None):
  self.status_code=status;self._data={} if data is None else data;self.headers=headers or {};self.content=(json_bytes(self._data) if content is None else content)
 def json(self):
  if isinstance(self._data,Exception):raise self._data
  return self._data
def json_bytes(x):
 import json
 return json.dumps(x).encode()
class Session:
 def __init__(self,seq):self.seq=list(seq);self.calls=[]
 def request(self,*a,**k):
  self.calls.append((a,k));x=self.seq.pop(0)
  if isinstance(x,Exception):raise x
  return x
@pytest.fixture
def store(tmp_path):return ConnectorStateStore(tmp_path/'c.sqlite3',vault=Vault())
def gateway(store,seq):return ConnectorGateway(store,session=Session(seq),sleep=lambda _:None,random_fn=lambda:0.5)

def test_drive_manifest_read_scope_remains_least_privilege():
 m=drive_manifest();m.validate();assert m.required_oauth_scopes==('https://www.googleapis.com/auth/drive.readonly',);assert all(o.effect=='read' for o in m.operations if o.name in {'drive.files.list','drive.files.search','drive.files.metadata','drive.files.read','drive.files.download','drive.files.export'})
def test_drive_manifest_has_scope_reason_and_limits():
 m=drive_manifest();assert dict(m.scope_reasons)[m.required_oauth_scopes[0]] and m.limit('max_file_bytes')==10*1024*1024
def test_sheets_manifest_read_scope_remains_least_privilege():
 m=sheets_manifest();m.validate();assert m.required_oauth_scopes==('https://www.googleapis.com/auth/spreadsheets.readonly',);assert all(o.effect=='read' for o in m.operations if o.name.startswith('sheets.') and o.name not in {'sheets.spreadsheets.create','sheets.values.update','sheets.values.append'})
def test_drive_list_and_search(store):
 g=gateway(store,[R(data={'files':[{'id':'1'}]}),R(data={'files':[{'id':'2'}]})]);a=GoogleDriveAdapter('t',gateway=g)
 assert a.list_files()['files'][0]['id']=='1';assert a.list_files(q="name contains 'x'")['files'][0]['id']=='2'
def test_drive_metadata(store):
 g=gateway(store,[R(data={'id':'f','name':'a.txt','mimeType':'text/plain'})]);a=GoogleDriveAdapter('t',gateway=g);assert a.get_metadata('f')['name']=='a.txt'
def test_drive_pagination(store):
 g=gateway(store,[R(data={'files':[{'id':'1'}],'nextPageToken':'p2'}),R(data={'files':[{'id':'2'}]})]);a=GoogleDriveAdapter('t',gateway=g);r=a.list_all();assert [x['id'] for x in r['items']]==['1','2'] and r['pages']==2
def test_drive_cyclic_cursor(store):
 g=gateway(store,[R(data={'files':[],'nextPageToken':'x'}),R(data={'files':[],'nextPageToken':'x'})]);a=GoogleDriveAdapter('t',gateway=g)
 with pytest.raises(ConnectorError) as e:a.list_all()
 assert e.value.code=='cursor_cycle'
def test_drive_download(store):
 meta={'id':'f','name':'a.txt','mimeType':'text/plain','size':'5','md5Checksum':'abc','version':'2','modifiedTime':'now'};g=gateway(store,[R(data=meta),R(data={},content=b'hello')]);a=GoogleDriveAdapter('t',gateway=g);r=a.read_file('f');assert r['content']==b'hello' and r['provenance']['provider_file_id']=='f'
def test_drive_docs_export(store):
 meta={'id':'d','name':'Doc','mimeType':'application/vnd.google-apps.document'};g=gateway(store,[R(data=meta),R(data={},content=b'text')]);a=GoogleDriveAdapter('t',gateway=g);r=a.read_file('d');assert r['filename']=='Doc.txt' and r['media_type']=='text/plain'
def test_drive_sheet_handoff(store):
 meta={'id':'s','name':'Sheet','mimeType':'application/vnd.google-apps.spreadsheet'};a=GoogleDriveAdapter('t',gateway=gateway(store,[R(data=meta)]))
 with pytest.raises(ConnectorError) as e:a.read_file('s')
 assert e.value.code=='use_sheets_connector'
def test_drive_unsupported_type(store):
 meta={'id':'z','name':'zip','mimeType':'application/zip'};a=GoogleDriveAdapter('t',gateway=gateway(store,[R(data=meta)]))
 with pytest.raises(ConnectorError) as e:a.read_file('z')
 assert e.value.code=='unsupported_file_type'
def test_drive_oversized_metadata_rejected(store):
 meta={'id':'f','name':'x.pdf','mimeType':'application/pdf','size':str(20*1024*1024)};a=GoogleDriveAdapter('t',gateway=gateway(store,[R(data=meta)]))
 with pytest.raises(ConnectorError) as e:a.read_file('f')
 assert e.value.code=='content_too_large'
def test_drive_response_too_large_rejected(store):
 meta={'id':'f','name':'x.txt','mimeType':'text/plain','size':'1'};a=GoogleDriveAdapter('t',gateway=gateway(store,[R(data=meta),R(data={},content=b'x'*(10*1024*1024+1))]))
 with pytest.raises(ConnectorError) as e:a.read_file('f')
 assert e.value.code=='content_too_large'
def test_drive_not_found(store):
 a=GoogleDriveAdapter('t',gateway=gateway(store,[R(404,data={'error':{}})]))
 with pytest.raises(ConnectorError) as e:a.get_metadata('missing')
 assert e.value.code=='not_found'
def test_drive_permission_denied(store):
 a=GoogleDriveAdapter('t',gateway=gateway(store,[R(403,data={'error':{'reason':'forbidden'}})]))
 with pytest.raises(ConnectorError) as e:a.get_metadata('x')
 assert e.value.code=='permission_denied'
def test_drive_retry_after(store):
 g=gateway(store,[R(429,data={'error':{}},headers={'Retry-After':'0'}),R(data={'id':'x','name':'x','mimeType':'text/plain'})]);a=GoogleDriveAdapter('t',gateway=g);assert a.get_metadata('x')['id']=='x';assert len(g.session.calls)==2
def test_drive_timeout_cancellation(store):
 a=GoogleDriveAdapter('t',gateway=gateway(store,[R(data={'files':[]})]))
 with pytest.raises(ConnectorError) as e:a.list_files(cancelled=lambda:True)
 assert e.value.code=='cancelled'
def test_drive_malformed_list(store):
 a=GoogleDriveAdapter('t',gateway=gateway(store,[R(data={'files':'bad'})]))
 with pytest.raises(ConnectorError) as e:a.list_files()
 assert e.value.code=='invalid_response'

def test_valid_a1_range_bounds():
 b=validate_a1_range("'Data 1'!A1:C10");assert b['rows']==10 and b['columns']==3 and b['cells']==30
@pytest.mark.parametrize('value',['A:A','1:10','A0:B2','B2:A1','Sheet!A1:Z99999','bad'])
def test_invalid_or_oversized_a1(value):
 with pytest.raises(ConnectorError):validate_a1_range(value)
def test_formula_injection_safety():
 assert safe_cell_for_export('=CMD()').startswith("'") and safe_cell_for_export('@x').startswith("'") and safe_cell_for_export('hello')=='hello'
def test_sheets_metadata_and_worksheets(store):
 meta={'spreadsheetId':'s','properties':{'title':'T'},'sheets':[{'properties':{'sheetId':1,'title':'Data','index':0,'gridProperties':{}}}]};g=gateway(store,[R(data=meta),R(data=meta)]);a=GoogleSheetsAdapter('t',gateway=g);assert a.spreadsheet_metadata('s')['properties']['title']=='T';assert a.list_worksheets('s')[0]['title']=='Data'
def test_sheets_valid_range_modes(store):
 seq=[R(data={'range':'Data!A1:B2','values':[['1','=x'],['2','3']]}),R(data={'range':'Data!A1:B2','values':[[1,2]]}),R(data={'range':'Data!A1:B2','values':[['=A2']]})];a=GoogleSheetsAdapter('t',gateway=gateway(store,seq));assert a.read_values('s','Data!A1:B2',value_mode='formatted')['value_mode']=='formatted';assert a.read_values('s','Data!A1:B2',value_mode='unformatted')['value_mode']=='unformatted';assert a.read_values('s','Data!A1:B2',value_mode='formula')['value_mode']=='formula'
def test_sheets_empty_sheet(store):
 a=GoogleSheetsAdapter('t',gateway=gateway(store,[R(data={'range':'Data!A1:B2','values':[]})]));assert a.read_values('s','Data!A1:B2')['values']==[]
def test_sheets_batch_read(store):
 a=GoogleSheetsAdapter('t',gateway=gateway(store,[R(data={'valueRanges':[{'range':'A1:A1','values':[['x']]},{'range':'B1:B1','values':[['y']]}]})]));r=a.batch_read('s',['A1:A1','B1:B1']);assert len(r['value_ranges'])==2
def test_sheets_too_many_ranges(store):
 a=GoogleSheetsAdapter('t',gateway=gateway(store,[]))
 with pytest.raises(ConnectorError) as e:a.batch_read('s',['A1:A1']*11)
 assert e.value.code=='range_too_large'
def test_sheets_malformed_values(store):
 a=GoogleSheetsAdapter('t',gateway=gateway(store,[R(data={'range':'A1:A1','values':'bad'})]))
 with pytest.raises(ConnectorError) as e:a.read_values('s','A1:A1')
 assert e.value.code=='invalid_response'
def test_sheets_quota_maps(store):
 a=GoogleSheetsAdapter('t',gateway=gateway(store,[R(403,data={'error':{'errors':[{'reason':'quotaExceeded'}]}}),R(403,data={'error':{'errors':[{'reason':'quotaExceeded'}]}}),R(403,data={'error':{'errors':[{'reason':'quotaExceeded'}]}})]))
 with pytest.raises(ConnectorError) as e:a.read_values('s','A1:A1')
 assert e.value.code=='quota_exceeded'
def test_sheets_deadline(store):
 a=GoogleSheetsAdapter('t',gateway=gateway(store,[R(data={})]))
 with pytest.raises(ConnectorError) as e:a.read_values('s','A1:A1',deadline=time.time()-1)
 assert e.value.code=='deadline_exceeded'
