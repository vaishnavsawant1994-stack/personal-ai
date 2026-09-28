from __future__ import annotations
from tools.registry import Risk,Tool,VerificationResult
from tools.integrations import _connector_call


def _rid(p):
    rid=str(p.get('request_id') or '').strip()
    if not rid:raise ValueError('request_id is required for governed connector writes')
    return rid[:200]

def register(registry,adapters=None):
    adapters=adapters or {};drive=adapters.get('drive');sheets=adapters.get('sheets')
    if drive is not None and all(hasattr(drive,x) for x in ('create_file','upload_file','rename_file','update_content')):
        def create(p):return _connector_call(drive,'create_file',str(p['filename']),str(p['mime_type']),parent_id=p.get('parent_id'),provider_account=str(p['provider_account']),request_id=_rid(p),destination=f"{p.get('parent_id') or 'root'}/{p['filename']}")
        def upload(p):return _connector_call(drive,'upload_file',str(p['filename']),str(p['mime_type']),str(p.get('content','')),parent_id=p.get('parent_id'),provider_account=str(p['provider_account']),request_id=_rid(p),destination=f"{p.get('parent_id') or 'root'}/{p['filename']}")
        def rename(p):return _connector_call(drive,'rename_file',str(p['file_id']),str(p['new_name']),expected_name=str(p['expected_name']),expected_version=str(p['expected_version']),provider_account=str(p['provider_account']),request_id=_rid(p),destination=str(p['file_id']))
        def update(p):return _connector_call(drive,'update_content',str(p['file_id']),str(p['mime_type']),str(p.get('content','')),expected_version=str(p['expected_version']),provider_account=str(p['provider_account']),request_id=_rid(p),destination=str(p['file_id']))
        verify=lambda p,r:VerificationResult(bool(isinstance(r,dict) and r.get('verified')),str((r or {}).get('verification') or 'provider read-back verification'),dict((r or {}).get('verification') or {}) if isinstance((r or {}).get('verification'),dict) else {})
        common=dict(risk=Risk.EXTERNAL_SIDE_EFFECT,verifier=verify,verification_required=True,requires_reauth=True,minimum_risk=Risk.EXTERNAL_SIDE_EFFECT,prohibited_data_classifications=('secret','restricted'),connector_id='drive')
        registry.register(Tool('drive_create_file','Create a bounded Drive file; params: provider_account,request_id,filename,mime_type,parent_id. Requires approval and recent re-authentication.',create,capability='drive.files.create',rollback_description='No automatic rollback; removal remains prohibited in this batch.',**common))
        registry.register(Tool('drive_upload_file','Upload bounded textual content to Drive; params: provider_account,request_id,filename,mime_type,content,parent_id. Requires approval and recent re-authentication.',upload,capability='drive.files.upload',rollback_description='No automatic rollback; removal remains prohibited in this batch.',**common))
        registry.register(Tool('drive_rename_file','Rename an existing Drive file using expected name/version; params: provider_account,request_id,file_id,expected_name,expected_version,new_name.',rename,capability='drive.files.rename',rollback_description='A compensating rename would require a separate approved action; no hidden rollback.',**common))
        registry.register(Tool('drive_update_content','Replace bounded Drive file content using an expected provider version; params: provider_account,request_id,file_id,expected_version,mime_type,content.',update,capability='drive.files.update_content',rollback_description='Restoration requires a separately approved action and retained prior content; no hidden rollback.',**common))
    if sheets is not None and all(hasattr(sheets,x) for x in ('create_spreadsheet','update_values','append_values')):
        def create_sheet(p):return _connector_call(sheets,'create_spreadsheet',str(p['title']),worksheet_title=str(p.get('worksheet_title','Sheet1')),rows=int(p.get('rows',1000)),columns=int(p.get('columns',26)),provider_account=str(p['provider_account']),request_id=_rid(p),destination=str(p['title']))
        def update_values(p):return _connector_call(sheets,'update_values',str(p['spreadsheet_id']),str(p['range']),list(p['values']),provider_account=str(p['provider_account']),request_id=_rid(p),expected_current_hash=str(p['expected_current_hash']),expected_etag=p.get('expected_etag'),destination=f"{p['spreadsheet_id']}#{p['range']}")
        def append_values(p):return _connector_call(sheets,'append_values',str(p['spreadsheet_id']),str(p['range']),list(p['values']),provider_account=str(p['provider_account']),request_id=_rid(p),destination=f"{p['spreadsheet_id']}#{p['range']}")
        verify=lambda p,r:VerificationResult(bool(isinstance(r,dict) and r.get('verified')),str((r or {}).get('verification') or 'provider read-back verification'),dict((r or {}).get('verification') or {}) if isinstance((r or {}).get('verification'),dict) else {})
        common=dict(risk=Risk.EXTERNAL_SIDE_EFFECT,verifier=verify,verification_required=True,requires_reauth=True,minimum_risk=Risk.EXTERNAL_SIDE_EFFECT,prohibited_data_classifications=('secret','restricted'),connector_id='sheets')
        registry.register(Tool('sheets_create_spreadsheet','Create a bounded spreadsheet; params: provider_account,request_id,title,worksheet_title,rows,columns. Requires approval and recent re-authentication.',create_sheet,capability='sheets.spreadsheets.create',rollback_description='No automatic rollback because spreadsheet deletion is prohibited in this batch.',**common))
        registry.register(Tool('sheets_update_values','Update a bounded A1 range with RAW literal values; params: provider_account,request_id,spreadsheet_id,range,values,expected_current_hash,expected_etag. Requires approval and recent re-authentication.',update_values,capability='sheets.values.update',rollback_description='A compensating update requires separate approval and retained prior values; no hidden rollback.',**common))
        registry.register(Tool('sheets_append_values','Append bounded RAW literal rows; params: provider_account,request_id,spreadsheet_id,range,values. Requires approval and recent re-authentication.',append_values,capability='sheets.values.append',rollback_description='Append rollback is unavailable because clear/delete is prohibited in this batch.',**common))
