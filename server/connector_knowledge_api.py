from fastapi import APIRouter,Cookie,HTTPException
from pydantic import BaseModel,Field
from integrations.gateway import ConnectorError
from integrations.knowledge_bridge import ConnectorKnowledgeIngestor

class DriveKnowledgeBody(BaseModel):
    approved:bool=False
    access_class:str='owner'
    never_store:bool=False
    export_mime:str='text/plain'
class SheetsKnowledgeBody(BaseModel):
    approved:bool=False
    access_class:str='owner'
    never_store:bool=False
    range:str=Field(min_length=1,max_length=256)
    value_mode:str='formatted'
    spreadsheet_title:str|None=None
    worksheet_id:int|None=None
    worksheet_title:str|None=None
    modified_time:str|None=None
    version:str|None=None
    source_reference:str|None=None

def connector_knowledge_router(runtime,auth):
    router=APIRouter(); adapters=runtime.get('integration_adapters') or {}; knowledge=runtime.get('knowledge')
    @router.post('/drive/files/{file_id}/knowledge')
    def ingest_drive(file_id:str,body:DriveKnowledgeBody,pa_device:str|None=Cookie(default=None),pa_token:str|None=Cookie(default=None)):
        ctx=auth(pa_device,pa_token,'knowledge:write')
        if body.access_class=='private':auth(pa_device,pa_token,'knowledge:private')
        if not body.approved:raise HTTPException(409,'Explicit owner approval is required before Drive content can enter Knowledge')
        if knowledge is None or adapters.get('drive') is None:raise HTTPException(409,'Drive Knowledge ingestion is not available')
        try:return ConnectorKnowledgeIngestor(knowledge).ingest_drive(adapters['drive'],file_id,approved=True,owner_id='owner',device_id=pa_device,session_id=ctx.session_id,access_class=body.access_class,never_store=body.never_store,export_mime=body.export_mime)
        except PermissionError as exc:raise HTTPException(403,str(exc)) from exc
        except ConnectorError as exc:raise HTTPException(exc.http_status,exc.safe_message) from exc
        except (ValueError,KeyError) as exc:raise HTTPException(422,str(exc)) from exc
    @router.post('/sheets/{spreadsheet_id}/knowledge')
    def ingest_sheet(spreadsheet_id:str,body:SheetsKnowledgeBody,pa_device:str|None=Cookie(default=None),pa_token:str|None=Cookie(default=None)):
        ctx=auth(pa_device,pa_token,'knowledge:write')
        if body.access_class=='private':auth(pa_device,pa_token,'knowledge:private')
        if not body.approved:raise HTTPException(409,'Explicit owner approval is required before Sheets content can enter Knowledge')
        if knowledge is None or adapters.get('sheets') is None:raise HTTPException(409,'Sheets Knowledge ingestion is not available')
        try:return ConnectorKnowledgeIngestor(knowledge).ingest_sheet_range(adapters['sheets'],spreadsheet_id,body.range,approved=True,owner_id='owner',device_id=pa_device,session_id=ctx.session_id,access_class=body.access_class,never_store=body.never_store,value_mode=body.value_mode,spreadsheet_title=body.spreadsheet_title,worksheet_id=body.worksheet_id,worksheet_title=body.worksheet_title,modified_time=body.modified_time,version=body.version,source_reference=body.source_reference)
        except PermissionError as exc:raise HTTPException(403,str(exc)) from exc
        except ConnectorError as exc:raise HTTPException(exc.http_status,exc.safe_message) from exc
        except (ValueError,KeyError) as exc:raise HTTPException(422,str(exc)) from exc
    return router
