import pytest
from integrations.knowledge_bridge import ConnectorKnowledgeIngestor

class K:
 def __init__(self):self.calls=[];self.version=0
 def ingest(self,**kw):self.calls.append(kw);self.version+=1;return {'id':'k'+str(self.version),'version':self.version,'metadata':kw.get('metadata')}
class Drive:
 def __init__(self):self.events=[];self.n=0
 def audit(self,event_type,**kw):self.events.append((event_type,kw))
 def read_file(self,file_id,**ctx):self.n+=1;return {'filename':'x.txt','content':('v'+str(self.n)).encode(),'media_type':'text/plain','provenance':{'connector_id':'drive','provider':'google','provider_file_id':file_id,'version':str(self.n),'modified_time':'t'+str(self.n),'checksum':'c'+str(self.n),'source_reference':'https://drive/x'}}
class Sheets:
 def __init__(self):self.events=[]
 def audit(self,event_type,**kw):self.events.append((event_type,kw))
 def read_values(self,sid,rng,**ctx):return {'spreadsheet_id':sid,'range':rng,'values':[['=BAD','ok'],['1','2']],'value_mode':ctx.get('value_mode','formatted'),'bounds':{'start_row':1,'end_row':2,'start_column':1,'end_column':2},'retrieval_time':1.0}

def auth():return dict(approved=True,owner_id='owner',device_id='d',session_id='s')
def test_drive_requires_explicit_approval():
 with pytest.raises(PermissionError):ConnectorKnowledgeIngestor(K()).ingest_drive(Drive(),'f',owner_id='owner',device_id='d',session_id='s')
def test_never_store_rejected():
 with pytest.raises(PermissionError):ConnectorKnowledgeIngestor(K()).ingest_drive(Drive(),'f',never_store=True,**auth())
def test_owner_device_session_required():
 with pytest.raises(PermissionError):ConnectorKnowledgeIngestor(K()).ingest_drive(Drive(),'f',approved=True,owner_id='owner',device_id=None,session_id='s')
def test_drive_provenance_and_authority_preserved():
 k=K();d=Drive();doc=ConnectorKnowledgeIngestor(k).ingest_drive(d,'f',access_class='owner',**auth());m=k.calls[0]['metadata'];assert m['provider_file_id']=='f' and m['authorized_device_id']=='d' and k.calls[0]['source']=='google-drive:f';assert doc['version']==1
def test_drive_source_update_relies_on_knowledge_lineage_not_provider_mutation():
 k=K();d=Drive();b=ConnectorKnowledgeIngestor(k);b.ingest_drive(d,'f',**auth());b.ingest_drive(d,'f',**auth());assert len(k.calls)==2 and k.calls[0]['source']==k.calls[1]['source'] and not hasattr(d,'delete')
def test_sheets_range_provenance():
 k=K();s=Sheets();ConnectorKnowledgeIngestor(k).ingest_sheet_range(s,'sid','Data!A1:B2',spreadsheet_title='Budget',worksheet_id=7,worksheet_title='Data',version='3',modified_time='now',source_reference='https://sheets/x',**auth());m=k.calls[0]['metadata'];assert m['provider_spreadsheet_id']=='sid' and m['range']=='Data!A1:B2' and m['worksheet_id']==7 and m['version']=='3'
def test_sheets_formula_injection_safe_csv():
 k=K();ConnectorKnowledgeIngestor(k).ingest_sheet_range(Sheets(),'sid','A1:B2',**auth());text=k.calls[0]['data'].decode();assert "'=BAD" in text and '=BAD' in text
def test_no_automatic_bulk_ingestion_api():
 assert not hasattr(ConnectorKnowledgeIngestor,'ingest_all_drive')
def test_sensitive_external_model_routing_fails_closed():
 with pytest.raises(PermissionError):ConnectorKnowledgeIngestor.validate_model_routing('private',external_model=True,policy_allows_external=False)
def test_sensitive_external_model_can_be_explicitly_allowed():
 assert ConnectorKnowledgeIngestor.validate_model_routing('private',external_model=True,policy_allows_external=True)
def test_audit_contains_ids_not_content():
 k=K();s=Sheets();ConnectorKnowledgeIngestor(k).ingest_sheet_range(s,'sid','A1:B2',**auth());payloads=[x[1].get('payload',{}) for x in s.events];blob=str(payloads);assert 'sid' in blob and '=BAD' not in blob and 'ok' not in blob
def test_ingestion_failure_audited():
 class Bad(Drive):
  def read_file(self,*a,**k):raise RuntimeError('content secret')
 b=Bad()
 with pytest.raises(RuntimeError):ConnectorKnowledgeIngestor(K()).ingest_drive(b,'f',**auth())
 assert b.events[-1][0]=='knowledge.ingestion.failed' and 'secret' not in str(b.events[-1])
