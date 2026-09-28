from __future__ import annotations
import hashlib, re, time
from integrations.adapters import BearerREST
from integrations.contracts import drive_manifest, sheets_manifest
from integrations.gateway import ConnectorError

class GoogleDriveAdapter(BearerREST):
    manifest=drive_manifest()
    FILE_FIELDS='id,name,mimeType,parents,owners(displayName,emailAddress),createdTime,modifiedTime,size,md5Checksum,version,webViewLink'
    MAX_FILE_BYTES=10*1024*1024
    GOOGLE_DOC='application/vnd.google-apps.document'; GOOGLE_SHEET='application/vnd.google-apps.spreadsheet'
    DOWNLOADABLE={'text/plain','text/csv','application/json','application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
    EXPORTS={GOOGLE_DOC:{'text/plain':'.txt','application/pdf':'.pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'.docx'}}
    def __init__(self,token,*,gateway=None):super().__init__('https://www.googleapis.com/drive/v3',token,gateway=gateway,connector_id='drive')
    def _ctx(self,ctx):return {k:ctx.get(k) for k in ('owner_id','device_id','session_id') if ctx.get(k) is not None}
    def list_files(self,q='',page_size=100,page_token=None,*,cancelled=None,deadline=None,**ctx):
        page_size=max(1,min(int(page_size),1000));params={'pageSize':page_size,'fields':f'nextPageToken,files({self.FILE_FIELDS})','spaces':'drive'}
        if q:params['q']=str(q)[:1000]
        if page_token:params['pageToken']=str(page_token)[:4096]
        op=self.manifest.operation('drive.files.search' if q else 'drive.files.list')
        out=self.request('GET','files',params=params,operation=op,operation_parameters={'query':str(q)[:1000],'page_size':page_size},cancelled=cancelled,deadline=deadline,**ctx)
        if not isinstance(out,dict) or not isinstance(out.get('files',[]),list):raise ConnectorError('invalid_response','Drive returned malformed file metadata.','invalid_response',502,False)
        self.audit('drive.search' if q else 'drive.list',payload={'count':len(out.get('files',[])),'query_hash':hashlib.sha256(str(q).encode()).hexdigest() if q else ''},**self._ctx(ctx));return out
    def list_all(self,q='',*,cancelled=None,deadline=None,**ctx):
        if not self.gateway:return self.list_files(q=q,cancelled=cancelled,deadline=deadline,**ctx)
        op=self.manifest.operation('drive.files.search' if q else 'drive.files.list')
        return self.gateway.paginate(lambda cur:self.list_files(q=q,page_token=cur,cancelled=cancelled,deadline=deadline,**ctx),op,cancelled=cancelled,deadline=deadline)
    def get_metadata(self,file_id,**ctx):
        fid=str(file_id).strip();
        if not fid:raise ValueError('file_id is required')
        out=self.request('GET',f'files/{fid}',params={'fields':self.FILE_FIELDS},operation=self.manifest.operation('drive.files.metadata'),operation_parameters={'file_id':fid},**ctx)
        if not isinstance(out,dict) or str(out.get('id') or '')!=fid:raise ConnectorError('invalid_response','Drive returned malformed file metadata.','invalid_response',502,False)
        self.audit('drive.metadata',payload={'file_id':fid,'mime_type':out.get('mimeType'),'version':out.get('version')},**self._ctx(ctx));return out
    def _provenance(self,meta,*,retrieved_at=None):
        owners=meta.get('owners') or []; owner=owners[0] if owners and isinstance(owners[0],dict) else {}
        return {'connector_id':'drive','provider':'google','provider_file_id':meta.get('id'),'name':meta.get('name'),'mime_type':meta.get('mimeType'),'source_account':owner.get('emailAddress') or owner.get('displayName'),'created_time':meta.get('createdTime'),'modified_time':meta.get('modifiedTime'),'size':meta.get('size'),'checksum':meta.get('md5Checksum'),'version':meta.get('version'),'source_reference':meta.get('webViewLink'),'retrieval_time':retrieved_at or time.time()}
    def read_file(self,file_id,*,export_mime='text/plain',cancelled=None,deadline=None,**ctx):
        meta=self.get_metadata(file_id,cancelled=cancelled,deadline=deadline,**ctx);mime=str(meta.get('mimeType') or '')
        if mime==self.GOOGLE_SHEET:raise ConnectorError('use_sheets_connector','Google Sheets content must be read through the governed Sheets connector.','degraded',422,False)
        if mime==self.GOOGLE_DOC:
            allowed=self.EXPORTS[self.GOOGLE_DOC]
            if export_mime not in allowed:raise ConnectorError('unsupported_file_type','The requested Google Docs export type is not supported.','degraded',415,False)
            content=self.request('GET',f'files/{file_id}/export',params={'mimeType':export_mime},operation=self.manifest.operation('drive.files.export'),operation_parameters={'file_id':file_id,'export_mime':export_mime},response_mode='bytes',max_response_bytes=self.MAX_FILE_BYTES,cancelled=cancelled,deadline=deadline,**ctx)
            filename=str(meta.get('name') or file_id)+allowed[export_mime]
            event='drive.export'
        elif mime in self.DOWNLOADABLE:
            size=int(meta.get('size') or 0)
            if size and size>self.MAX_FILE_BYTES:raise ConnectorError('content_too_large','The Drive file exceeds the configured content limit.','degraded',413,False)
            content=self.request('GET',f'files/{file_id}',params={'alt':'media'},operation=self.manifest.operation('drive.files.download'),operation_parameters={'file_id':file_id},response_mode='bytes',max_response_bytes=self.MAX_FILE_BYTES,cancelled=cancelled,deadline=deadline,**ctx)
            filename=str(meta.get('name') or file_id);event='drive.download'
        else:
            self.audit('drive.unsupported_type',payload={'file_id':str(file_id),'mime_type':mime},**self._ctx(ctx));raise ConnectorError('unsupported_file_type','This Drive file type is not supported for safe read/ingestion.','degraded',415,False)
        self.audit(event,payload={'file_id':str(file_id),'mime_type':mime,'bytes':len(content),'version':meta.get('version')},**self._ctx(ctx))
        return {'filename':filename,'content':content,'media_type':export_mime if mime==self.GOOGLE_DOC else mime,'metadata':meta,'provenance':self._provenance(meta)}

_A1_RE=re.compile(r"^(?:(?:'([^']|'')+'|([A-Za-z0-9_ .-]+))!)?([A-Z]{1,3})([1-9][0-9]*)(?::([A-Z]{1,3})([1-9][0-9]*))?$")
def _col_number(col):
    n=0
    for c in col:n=n*26+(ord(c)-64)
    return n
def validate_a1_range(value,max_rows=1000,max_columns=100,max_cells=50000):
    text=str(value or '').strip();m=_A1_RE.fullmatch(text)
    if not m:raise ConnectorError('invalid_range','An explicit bounded A1 range is required.','degraded',422,False)
    c1,r1,c2,r2=m.group(3),int(m.group(4)),m.group(5) or m.group(3),int(m.group(6) or m.group(4));c1n,c2n=_col_number(c1),_col_number(c2)
    if r2<r1 or c2n<c1n:raise ConnectorError('invalid_range','The A1 range bounds are invalid.','degraded',422,False)
    rows=r2-r1+1;cols=c2n-c1n+1;cells=rows*cols
    if rows>max_rows or cols>max_columns or cells>max_cells:raise ConnectorError('range_too_large','The requested sheet range exceeds configured limits.','degraded',413,False)
    return {'range':text,'start_row':r1,'end_row':r2,'start_column':c1n,'end_column':c2n,'rows':rows,'columns':cols,'cells':cells}
def safe_cell_for_export(value):
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):return "'"+value
    return value

class GoogleSheetsAdapter(BearerREST):
    manifest=sheets_manifest();MAX_WORKSHEETS=100;MAX_RANGES=10;MAX_ROWS=1000;MAX_COLUMNS=100;MAX_CELLS=50000;MAX_RESPONSE_BYTES=2*1024*1024
    def __init__(self,token,*,gateway=None):super().__init__('https://sheets.googleapis.com/v4',token,gateway=gateway,connector_id='sheets')
    def _ctx(self,ctx):return {k:ctx.get(k) for k in ('owner_id','device_id','session_id') if ctx.get(k) is not None}
    def spreadsheet_metadata(self,spreadsheet_id,**ctx):
        sid=str(spreadsheet_id).strip();out=self.request('GET',f'spreadsheets/{sid}',params={'includeGridData':'false','fields':'spreadsheetId,properties(title,locale,timeZone),sheets(properties(sheetId,title,index,gridProperties)),spreadsheetUrl'},operation=self.manifest.operation('sheets.spreadsheets.metadata'),operation_parameters={'spreadsheet_id':sid},max_response_bytes=self.MAX_RESPONSE_BYTES,**ctx)
        if not isinstance(out,dict) or str(out.get('spreadsheetId') or '')!=sid:raise ConnectorError('invalid_response','Sheets returned malformed spreadsheet metadata.','invalid_response',502,False)
        sheets=out.get('sheets') or []
        if not isinstance(sheets,list) or len(sheets)>self.MAX_WORKSHEETS:raise ConnectorError('range_too_large','Spreadsheet contains more worksheets than allowed.','degraded',413,False)
        self.audit('sheets.metadata',payload={'spreadsheet_id':sid,'worksheet_count':len(sheets)},**self._ctx(ctx));return out
    def list_worksheets(self,spreadsheet_id,**ctx):
        meta=self.spreadsheet_metadata(spreadsheet_id,**ctx);items=[]
        for s in meta.get('sheets',[]):
            p=s.get('properties') if isinstance(s,dict) else None
            if isinstance(p,dict):items.append({'sheet_id':p.get('sheetId'),'title':p.get('title'),'index':p.get('index'),'grid_properties':p.get('gridProperties') or {}})
        self.audit('sheets.worksheets.list',payload={'spreadsheet_id':str(spreadsheet_id),'count':len(items)},**self._ctx(ctx));return items
    def read_values(self,spreadsheet_id,a1_range,*,value_mode='formatted',cancelled=None,deadline=None,**ctx):
        bounds=validate_a1_range(a1_range,self.MAX_ROWS,self.MAX_COLUMNS,self.MAX_CELLS);mode={'formatted':'FORMATTED_VALUE','unformatted':'UNFORMATTED_VALUE','formula':'FORMULA'}.get(str(value_mode).lower())
        if not mode:raise ConnectorError('invalid_value_mode','Value mode must be formatted, unformatted or formula.','degraded',422,False)
        sid=str(spreadsheet_id).strip();params={'valueRenderOption':mode,'majorDimension':'ROWS'}
        out=self.request('GET',f'spreadsheets/{sid}/values/{bounds["range"]}',params=params,operation=self.manifest.operation('sheets.values.read'),operation_parameters={'spreadsheet_id':sid,'range':bounds['range'],'value_mode':value_mode},max_response_bytes=self.MAX_RESPONSE_BYTES,cancelled=cancelled,deadline=deadline,**ctx)
        if not isinstance(out,dict) or not isinstance(out.get('values',[]),list):raise ConnectorError('invalid_response','Sheets returned malformed values.','invalid_response',502,False)
        values=out.get('values') or []
        actual_cells=sum(len(r) for r in values if isinstance(r,list));
        if actual_cells>self.MAX_CELLS:raise ConnectorError('range_too_large','The returned sheet values exceed configured limits.','degraded',413,False)
        result={'range':str(out.get('range') or bounds['range']),'major_dimension':str(out.get('majorDimension') or 'ROWS'),'values':values,'value_mode':str(value_mode).lower(),'bounds':bounds,'retrieval_time':time.time(),'spreadsheet_id':sid}
        self.audit('sheets.values.read',payload={'spreadsheet_id':sid,'range':bounds['range'],'rows':len(values),'cells':actual_cells,'value_mode':str(value_mode).lower()},**self._ctx(ctx));return result
    def batch_read(self,spreadsheet_id,ranges,*,value_mode='formatted',cancelled=None,deadline=None,**ctx):
        ranges=list(ranges or [])
        if not 1<=len(ranges)<=self.MAX_RANGES:raise ConnectorError('range_too_large','Batch reads require 1 to 10 ranges.','degraded',413,False)
        checked=[validate_a1_range(r,self.MAX_ROWS,self.MAX_COLUMNS,self.MAX_CELLS) for r in ranges]
        if sum(x['cells'] for x in checked)>self.MAX_CELLS:raise ConnectorError('range_too_large','Combined sheet ranges exceed configured limits.','degraded',413,False)
        mode={'formatted':'FORMATTED_VALUE','unformatted':'UNFORMATTED_VALUE','formula':'FORMULA'}.get(str(value_mode).lower())
        if not mode:raise ConnectorError('invalid_value_mode','Value mode must be formatted, unformatted or formula.','degraded',422,False)
        sid=str(spreadsheet_id).strip();params=[('ranges',x['range']) for x in checked]+[('valueRenderOption',mode),('majorDimension','ROWS')]
        out=self.request('GET',f'spreadsheets/{sid}/values:batchGet',params=params,operation=self.manifest.operation('sheets.values.batch_read'),operation_parameters={'spreadsheet_id':sid,'ranges':[x['range'] for x in checked],'value_mode':value_mode},max_response_bytes=self.MAX_RESPONSE_BYTES,cancelled=cancelled,deadline=deadline,**ctx)
        vrs=out.get('valueRanges') if isinstance(out,dict) else None
        if not isinstance(vrs,list):raise ConnectorError('invalid_response','Sheets returned malformed batch values.','invalid_response',502,False)
        total=sum(len(r) for vr in vrs if isinstance(vr,dict) for r in (vr.get('values') or []) if isinstance(r,list))
        if total>self.MAX_CELLS:raise ConnectorError('range_too_large','Returned batch values exceed configured limits.','degraded',413,False)
        self.audit('sheets.values.batch_read',payload={'spreadsheet_id':sid,'ranges':[x['range'] for x in checked],'cells':total,'value_mode':str(value_mode).lower()},**self._ctx(ctx));return {'spreadsheet_id':sid,'value_ranges':vrs,'value_mode':str(value_mode).lower(),'retrieval_time':time.time()}
