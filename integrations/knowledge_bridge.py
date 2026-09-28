from __future__ import annotations
import csv, io, json
from integrations.google_read import safe_cell_for_export
from integrations.gateway import ConnectorError

class ConnectorKnowledgeIngestor:
    def __init__(self,knowledge_store):self.knowledge=knowledge_store
    @staticmethod
    def _authorize(*,approved,owner_id,device_id,session_id,never_store=False):
        if never_store:raise PermissionError('NEVER_STORE content cannot be ingested into Knowledge')
        if not approved:raise PermissionError('Connector Knowledge ingestion requires explicit owner approval')
        if not owner_id or not device_id or not session_id:raise PermissionError('Owner, trusted device and browser session are required for connector ingestion')
    @staticmethod
    def validate_model_routing(access_class,*,external_model=False,policy_allows_external=False):
        if external_model and str(access_class).lower() in {'private','sensitive','restricted','secret'} and not policy_allows_external:
            raise PermissionError('Sensitive connector content cannot be routed to an external model by default')
        return True
    def ingest_drive(self,adapter,file_id,*,approved=False,owner_id='owner',device_id=None,session_id=None,access_class='owner',never_store=False,export_mime='text/plain'):
        self._authorize(approved=approved,owner_id=owner_id,device_id=device_id,session_id=session_id,never_store=never_store)
        adapter.audit('knowledge.ingestion.requested',owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'source':'drive','file_id':str(file_id),'access_class':access_class})
        try:
            item=adapter.read_file(file_id,export_mime=export_mime,owner_id=owner_id,device_id=device_id,session_id=session_id)
            meta={**dict(item.get('provenance') or {}),'authorized_owner_id':owner_id,'authorized_device_id':device_id,'authorized_session_id':session_id,'access_classification':access_class}
            doc=self.knowledge.ingest(filename=item['filename'],data=item['content'],media_type=item.get('media_type') or 'application/octet-stream',source=f'google-drive:{file_id}',access_class=access_class,metadata=meta)
            adapter.audit('knowledge.ingestion.completed',owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'source':'drive','file_id':str(file_id),'knowledge_document_id':doc.get('id'),'version':doc.get('version')})
            return doc
        except Exception:
            adapter.audit('knowledge.ingestion.failed',owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'source':'drive','file_id':str(file_id)})
            raise
    def ingest_sheet_range(self,adapter,spreadsheet_id,a1_range,*,approved=False,owner_id='owner',device_id=None,session_id=None,access_class='owner',never_store=False,value_mode='formatted',spreadsheet_title=None,worksheet_id=None,worksheet_title=None,modified_time=None,version=None,source_reference=None):
        self._authorize(approved=approved,owner_id=owner_id,device_id=device_id,session_id=session_id,never_store=never_store)
        adapter.audit('knowledge.ingestion.requested',owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'source':'sheets','spreadsheet_id':str(spreadsheet_id),'range':str(a1_range),'access_class':access_class})
        try:
            result=adapter.read_values(spreadsheet_id,a1_range,value_mode=value_mode,owner_id=owner_id,device_id=device_id,session_id=session_id)
            out=io.StringIO(newline='');w=csv.writer(out)
            for row in result.get('values') or []:w.writerow([safe_cell_for_export(v) for v in (row if isinstance(row,list) else [row])])
            data=out.getvalue().encode('utf-8')
            source=f'google-sheets:{spreadsheet_id}:{result["range"]}'
            meta={'connector_id':'sheets','provider':'google','provider_spreadsheet_id':str(spreadsheet_id),'spreadsheet_title':spreadsheet_title,'worksheet_id':worksheet_id,'worksheet_title':worksheet_title,'range':result['range'],'bounds':result['bounds'],'retrieval_time':result['retrieval_time'],'modified_time':modified_time,'version':version,'source_reference':source_reference,'value_mode':result['value_mode'],'authorized_owner_id':owner_id,'authorized_device_id':device_id,'authorized_session_id':session_id,'access_classification':access_class}
            filename=f'{spreadsheet_title or spreadsheet_id}-{str(result["range"]).replace("!","-").replace(":","-")}.csv'
            doc=self.knowledge.ingest(filename=filename,data=data,media_type='text/csv',source=source,access_class=access_class,metadata=meta)
            adapter.audit('knowledge.ingestion.completed',owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'source':'sheets','spreadsheet_id':str(spreadsheet_id),'range':result['range'],'knowledge_document_id':doc.get('id'),'version':doc.get('version')})
            return doc
        except Exception:
            adapter.audit('knowledge.ingestion.failed',owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'source':'sheets','spreadsheet_id':str(spreadsheet_id),'range':str(a1_range)})
            raise
