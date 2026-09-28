from __future__ import annotations

import hashlib
import json

from integrations.gateway import ConnectorError
from integrations.google_read import (
    GoogleDriveAdapter,
    GoogleSheetsAdapter,
    validate_a1_range,
)

SAFE_MIME={'text/plain','text/csv','application/json','application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}

def _name(value):
    v=str(value or '').strip()
    if not v or len(v)>255 or v in {'.','..'} or any(x in v for x in '\r\n\x00'):raise ConnectorError('invalid_name','A valid file or spreadsheet name is required.','degraded',422,False)
    return v

def _account(value):
    v=str(value or '').strip()
    if not v or len(v)>320:raise ConnectorError('account_required','The connected provider account must be explicitly bound to this write.','degraded',422,False)
    return v

def _request_id(value):
    v=str(value or '').strip()
    if not v or len(v)>200:raise ConnectorError('idempotency_required','A bounded request_id is required for connector writes.','degraded',422,False)
    return v

def _bytes(content):
    if isinstance(content,bytes):return content
    if isinstance(content,str):return content.encode('utf-8')
    raise ConnectorError('invalid_content','Write content must be text or bytes.','degraded',422,False)

def _sha(data):return hashlib.sha256(data).hexdigest()
def _md5(data):return hashlib.md5(data, usedforsecurity=False).hexdigest()
def _opid(result):return str(result.get('_personal_ai_operation_id') or '') if isinstance(result,dict) else ''

def _literal_values(values,max_rows,max_cols,max_cells,max_bytes):
    if not isinstance(values,list) or not values or any(not isinstance(r,list) for r in values):raise ConnectorError('invalid_values','Values must be a non-empty two-dimensional array.','degraded',422,False)
    rows=len(values);cols=max((len(r) for r in values),default=0);cells=sum(len(r) for r in values)
    if rows>max_rows or cols>max_cols or cells>max_cells:raise ConnectorError('range_too_large','The write exceeds configured row, column or cell limits.','degraded',413,False)
    raw=json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()
    if len(raw)>max_bytes:raise ConnectorError('content_too_large','The write payload exceeds the configured byte limit.','degraded',413,False)
    for row in values:
        for value in row:
            if isinstance(value,(dict,list,tuple,set)):raise ConnectorError('invalid_values','Cell values must be scalar RAW data.','degraded',422,False)
    return values,rows,cols,cells,len(raw)

class GoogleDriveWriteAdapter(GoogleDriveAdapter):
    UPLOAD_BASE='https://www.googleapis.com/upload/drive/v3'
    def __init__(self,token,*,gateway=None,granted_scopes=None):super().__init__(token,gateway=gateway);self.granted_scopes=None if granted_scopes is None else set(granted_scopes)
    def _finish(self,result,verified,evidence):
        oid=_opid(result)
        if oid and self.gateway:
            self.gateway.state.transition_operation(oid,'verified' if verified else 'failed',verification_state='verified' if verified else 'verification_failed',verification_evidence=evidence)
            self.gateway.state.audit('verification.succeeded' if verified else 'verification.failed',connector_id='drive',correlation_id=oid,payload={'operation':self.gateway.state.operation(oid)['operation_name'],**evidence})
        if not verified:raise ConnectorError('verification_failed','Drive did not verify the requested write.','verification_failed',409,False)
        return {**result,'verified':True,'verification':evidence}
    def create_file(self,name,mime_type,*,parent_id=None,provider_account,request_id,cancelled=None,deadline=None,**ctx):
        ctx.pop('destination',None)
        name=_name(name);acct=_account(provider_account);rid=_request_id(request_id);mime=str(mime_type or '').strip()
        if mime not in SAFE_MIME:raise ConnectorError('unsupported_file_type','This MIME type is not allowed for Drive creation.','degraded',415,False)
        meta={'name':name,'mimeType':mime,'appProperties':{'personalAiRequestHash':hashlib.sha256(rid.encode()).hexdigest()}}
        if parent_id:meta['parents']=[str(parent_id)]
        result=self.request('POST','files',params={'fields':self.FILE_FIELDS},json=meta,operation=self.manifest.operation('drive.files.create'),operation_parameters={'name':name,'mime_type':mime,'parent_id':str(parent_id or ''),'provider_account':acct,'request_id_hash':hashlib.sha256(rid.encode()).hexdigest()},destination=f'{parent_id or "root"}/{name}',idempotency_key=f'drive-create:{acct}:{rid}',provider_account=acct,cancelled=cancelled,deadline=deadline,**ctx)
        fid=str(result.get('id') or ''); verified=False;evidence={'provider_file_id':fid,'rollback_available':False}
        if fid:
            check=self.get_metadata(fid,**ctx); verified=check.get('name')==name and check.get('mimeType')==mime and (not parent_id or str(parent_id) in (check.get('parents') or []));evidence.update({'name':check.get('name'),'mime_type':check.get('mimeType'),'version':check.get('version')})
        return self._finish(result,verified,evidence)
    def upload_file(self,name,mime_type,content,*,parent_id=None,provider_account,request_id,cancelled=None,deadline=None,**ctx):
        ctx.pop('destination',None)
        name=_name(name);acct=_account(provider_account);rid=_request_id(request_id);mime=str(mime_type or '').strip();data=_bytes(content)
        if mime not in SAFE_MIME:raise ConnectorError('unsupported_file_type','This MIME type is not allowed for Drive upload.','degraded',415,False)
        if len(data)>self.MAX_FILE_BYTES:raise ConnectorError('content_too_large','The Drive upload exceeds the configured content limit.','degraded',413,False)
        checksum=_sha(data); boundary='pa_'+hashlib.sha256(rid.encode()).hexdigest()[:24]
        meta={'name':name,'mimeType':mime,'appProperties':{'personalAiRequestHash':hashlib.sha256(rid.encode()).hexdigest()}}
        if parent_id:meta['parents']=[str(parent_id)]
        body=(f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()+json.dumps(meta,separators=(',',':')).encode()+f'\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n'.encode()+data+f'\r\n--{boundary}--\r\n'.encode())
        result=self.request('POST',f'{self.UPLOAD_BASE}/files',params={'uploadType':'multipart','fields':self.FILE_FIELDS},headers={'Content-Type':f'multipart/related; boundary={boundary}'},data=body,operation=self.manifest.operation('drive.files.upload'),operation_parameters={'name':name,'mime_type':mime,'parent_id':str(parent_id or ''),'provider_account':acct,'content_checksum':checksum,'size':len(data)},destination=f'{parent_id or "root"}/{name}',idempotency_key=f'drive-upload:{acct}:{rid}',provider_account=acct,content_checksum=checksum,cancelled=cancelled,deadline=deadline,**ctx)
        fid=str(result.get('id') or '');verified=False;evidence={'provider_file_id':fid,'content_checksum':checksum,'size':len(data),'rollback_available':False}
        if fid:
            check=self.get_metadata(fid,**ctx); provider_md5=str(check.get('md5Checksum') or ''); verified=check.get('name')==name and check.get('mimeType')==mime and (not parent_id or str(parent_id) in (check.get('parents') or [])) and (not check.get('size') or int(check['size'])==len(data)) and (not provider_md5 or provider_md5==_md5(data)); evidence.update({'version':check.get('version'),'provider_md5':provider_md5})
        return self._finish(result,verified,evidence)
    def rename_file(self,file_id,new_name,*,expected_name,expected_version,provider_account,request_id,cancelled=None,deadline=None,**ctx):
        ctx.pop('destination',None)
        fid=str(file_id).strip();name=_name(new_name);acct=_account(provider_account);rid=_request_id(request_id);before=self.get_metadata(fid,**ctx)
        if str(before.get('name'))!=str(expected_name) or str(before.get('version'))!=str(expected_version):
            self.audit('stale_version.conflict',payload={'file_id':fid,'expected_version':str(expected_version),'actual_version':str(before.get('version'))},**self._ctx(ctx));raise ConnectorError('precondition_conflict','Drive file changed since it was reviewed. Refresh before renaming.','degraded',409,False)
        headers={};etag=before.get('_provider_etag');
        if etag:headers['If-Match']=str(etag)
        result=self.request('PATCH',f'files/{fid}',params={'fields':self.FILE_FIELDS},headers=headers,json={'name':name},operation=self.manifest.operation('drive.files.rename'),operation_parameters={'file_id':fid,'expected_name':str(expected_name),'expected_version':str(expected_version),'new_name':name,'provider_account':acct},destination=fid,idempotency_key=f'drive-rename:{acct}:{rid}',provider_account=acct,cancelled=cancelled,deadline=deadline,**ctx)
        check=self.get_metadata(fid,**ctx);verified=check.get('name')==name and str(check.get('version'))!=str(expected_version);return self._finish(result,verified,{'provider_file_id':fid,'name':check.get('name'),'version':check.get('version'),'previous_name':str(expected_name),'rollback_available':False})
    def update_content(self,file_id,mime_type,content,*,expected_version,provider_account,request_id,cancelled=None,deadline=None,**ctx):
        ctx.pop('destination',None)
        fid=str(file_id).strip();acct=_account(provider_account);rid=_request_id(request_id);mime=str(mime_type or '').strip();data=_bytes(content)
        if mime not in SAFE_MIME:raise ConnectorError('unsupported_file_type','This MIME type is not allowed for Drive content update.','degraded',415,False)
        if len(data)>self.MAX_FILE_BYTES:raise ConnectorError('content_too_large','The Drive update exceeds the configured content limit.','degraded',413,False)
        before=self.get_metadata(fid,**ctx)
        if str(before.get('version'))!=str(expected_version):raise ConnectorError('precondition_conflict','Drive file changed since it was reviewed. Refresh before updating.','degraded',409,False)
        if str(before.get('mimeType') or '')!=mime:raise ConnectorError('mime_conflict','The requested content MIME type does not match the existing Drive file.','degraded',409,False)
        checksum=_sha(data);headers={'Content-Type':mime};etag=before.get('_provider_etag');
        if etag:headers['If-Match']=str(etag)
        result=self.request('PATCH',f'{self.UPLOAD_BASE}/files/{fid}',params={'uploadType':'media','fields':self.FILE_FIELDS},headers=headers,data=data,operation=self.manifest.operation('drive.files.update_content'),operation_parameters={'file_id':fid,'expected_version':str(expected_version),'mime_type':mime,'provider_account':acct,'content_checksum':checksum,'size':len(data)},destination=fid,idempotency_key=f'drive-content:{acct}:{rid}',provider_account=acct,content_checksum=checksum,cancelled=cancelled,deadline=deadline,**ctx)
        check=self.get_metadata(fid,**ctx);md5=str(check.get('md5Checksum') or '');verified=str(check.get('version'))!=str(expected_version) and (not check.get('size') or int(check['size'])==len(data)) and (not md5 or md5==_md5(data));return self._finish(result,verified,{'provider_file_id':fid,'version':check.get('version'),'content_checksum':checksum,'provider_md5':md5,'rollback_available':False})

class GoogleSheetsWriteAdapter(GoogleSheetsAdapter):
    def __init__(self,token,*,gateway=None,granted_scopes=None):super().__init__(token,gateway=gateway);self.granted_scopes=None if granted_scopes is None else set(granted_scopes)
    def _finish(self,result,verified,evidence):
        oid=_opid(result)
        if oid and self.gateway:self.gateway.state.transition_operation(oid,'verified' if verified else 'failed',verification_state='verified' if verified else 'verification_failed',verification_evidence=evidence);self.gateway.state.audit('verification.succeeded' if verified else 'verification.failed',connector_id='sheets',correlation_id=oid,payload=evidence)
        if not verified:raise ConnectorError('verification_failed','Sheets did not verify the requested write.','verification_failed',409,False)
        return {**result,'verified':True,'verification':evidence}
    @staticmethod
    def _hash_values(values):return hashlib.sha256(json.dumps(values,ensure_ascii=False,separators=(',',':'),sort_keys=False).encode()).hexdigest()
    def create_spreadsheet(self,title,*,worksheet_title='Sheet1',rows=1000,columns=26,provider_account,request_id,cancelled=None,deadline=None,**ctx):
        ctx.pop('destination',None)
        title=_name(title);ws=_name(worksheet_title);acct=_account(provider_account);rid=_request_id(request_id);rows=max(1,min(int(rows),self.MAX_ROWS));columns=max(1,min(int(columns),self.MAX_COLUMNS))
        body={'properties':{'title':title},'sheets':[{'properties':{'title':ws,'gridProperties':{'rowCount':rows,'columnCount':columns}}}]}
        result=self.request('POST','spreadsheets',json=body,operation=self.manifest.operation('sheets.spreadsheets.create'),operation_parameters={'title':title,'worksheet_title':ws,'rows':rows,'columns':columns,'provider_account':acct},destination=title,idempotency_key=f'sheets-create:{acct}:{rid}',provider_account=acct,cancelled=cancelled,deadline=deadline,**ctx)
        sid=str(result.get('spreadsheetId') or '');verified=False;evidence={'spreadsheet_id':sid,'rollback_available':False}
        if sid:
            meta=self.spreadsheet_metadata(sid,**ctx);verified=str((meta.get('properties') or {}).get('title'))==title;evidence['title']=(meta.get('properties') or {}).get('title')
        return self._finish(result,verified,evidence)
    def update_values(self,spreadsheet_id,a1_range,values,*,provider_account,request_id,expected_current_hash,expected_etag=None,cancelled=None,deadline=None,**ctx):
        ctx.pop('destination',None)
        sid=str(spreadsheet_id).strip();acct=_account(provider_account);rid=_request_id(request_id);bounds=validate_a1_range(a1_range,self.MAX_ROWS,self.MAX_COLUMNS,self.MAX_CELLS);vals,rows,cols,cells,_size=_literal_values(values,bounds['rows'],bounds['columns'],min(self.MAX_CELLS,10000),1024*1024)
        current=self.read_values(sid,bounds['range'],value_mode='unformatted',**ctx);curhash=self._hash_values(current.get('values') or [])
        if not expected_current_hash or curhash!=str(expected_current_hash):raise ConnectorError('precondition_conflict','Sheet values changed since they were reviewed. Refresh before updating.','degraded',409,False)
        headers={}
        if expected_etag:headers['If-Match']=str(expected_etag)
        checksum=self._hash_values(vals);result=self.request('PUT',f'spreadsheets/{sid}/values/{bounds["range"]}',params={'valueInputOption':'RAW','includeValuesInResponse':'true','responseValueRenderOption':'UNFORMATTED_VALUE'},headers=headers,json={'range':bounds['range'],'majorDimension':'ROWS','values':vals},operation=self.manifest.operation('sheets.values.update'),operation_parameters={'spreadsheet_id':sid,'range':bounds['range'],'provider_account':acct,'rows':rows,'columns':cols,'cells':cells,'content_checksum':checksum,'expected_current_hash':str(expected_current_hash)},destination=f'{sid}#{bounds["range"]}',idempotency_key=f'sheets-update:{acct}:{rid}',provider_account=acct,content_checksum=checksum,cancelled=cancelled,deadline=deadline,**ctx)
        after=self.read_values(sid,bounds['range'],value_mode='unformatted',**ctx);verified=self._hash_values(after.get('values') or [])==checksum;return self._finish(result,verified,{'spreadsheet_id':sid,'range':bounds['range'],'rows':rows,'columns':cols,'cells':cells,'content_checksum':checksum,'rollback_available':False})
    def append_values(self,spreadsheet_id,table_range,values,*,provider_account,request_id,cancelled=None,deadline=None,**ctx):
        ctx.pop('destination',None)
        sid=str(spreadsheet_id).strip();acct=_account(provider_account);rid=_request_id(request_id);bounds=validate_a1_range(table_range,self.MAX_ROWS,self.MAX_COLUMNS,self.MAX_CELLS);vals,rows,cols,cells,_size=_literal_values(values,min(500,bounds['rows']),bounds['columns'],min(10000,self.MAX_CELLS),1024*1024);checksum=self._hash_values(vals)
        result=self.request('POST',f'spreadsheets/{sid}/values/{bounds["range"]}:append',params={'valueInputOption':'RAW','insertDataOption':'INSERT_ROWS','includeValuesInResponse':'true','responseValueRenderOption':'UNFORMATTED_VALUE'},json={'majorDimension':'ROWS','values':vals},operation=self.manifest.operation('sheets.values.append'),operation_parameters={'spreadsheet_id':sid,'range':bounds['range'],'provider_account':acct,'rows':rows,'columns':cols,'cells':cells,'content_checksum':checksum},destination=f'{sid}#{bounds["range"]}',idempotency_key=f'sheets-append:{acct}:{rid}',provider_account=acct,content_checksum=checksum,cancelled=cancelled,deadline=deadline,**ctx)
        updates=result.get('updates') if isinstance(result,dict) else None;updated=str((updates or {}).get('updatedRange') or '')
        if not updated:return self._finish(result,False,{'spreadsheet_id':sid,'rollback_available':False})
        after=self.read_values(sid,updated,value_mode='unformatted',**ctx);verified=self._hash_values(after.get('values') or [])==checksum;return self._finish(result,verified,{'spreadsheet_id':sid,'updated_range':updated,'rows':rows,'cells':cells,'content_checksum':checksum,'rollback_available':False})
