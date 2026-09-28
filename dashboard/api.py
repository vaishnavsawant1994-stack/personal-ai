from __future__ import annotations
from fastapi import APIRouter,HTTPException,Header
from pydantic import BaseModel,Field
import uuid
from devices.gateway import DeviceCommand
class ActionRequest(BaseModel):tool:str;parameters:dict=Field(default_factory=dict)
class DeviceActionRequest(BaseModel):action:str;parameters:dict=Field(default_factory=dict);timeout:float=15

def dashboard_router(runtime,auth_device):
    r=APIRouter(prefix='/dashboard',tags=['dashboard'])
    def auth(a,d,scope='ai:chat'):auth_device(a,d,scope)
    @r.get('/status')
    def status(authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):
        auth(authorization,x_device_id,'device:read'); return {'automations':len(runtime['automations'].list()),'devices':len(runtime['device_registry'].list()),'online_devices':runtime['device_gateway'].online(),'integrations':runtime.get('integrations').list() if runtime.get('integrations') else [],'memory_nodes':len(runtime['second_brain'].graph().get('nodes',[])),'voice_state':'active' if getattr(runtime.get('voice'),'thread',None) and runtime['voice'].thread.is_alive() else 'idle','security':{'vault':'keychain-backed' if runtime.get('vault') else 'unavailable','autonomy':runtime['tools'].settings.autonomy_mode}}
    @r.get('/devices')
    def devices(authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):auth(authorization,x_device_id,'device:read');return runtime['device_registry'].list()
    @r.get('/automations')
    def automations(authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):auth(authorization,x_device_id,'workflow:read');return runtime['automations'].list()
    @r.get('/memory')
    def memory(authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):auth(authorization,x_device_id,'memory:sensitive');return runtime['second_brain'].graph()
    @r.post('/tool')
    def tool(req:ActionRequest,authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):
        auth(authorization,x_device_id,'ai:chat')
        raise HTTPException(409,'Direct dashboard tool execution is disabled; use the canonical governed Personal AI runtime')
    @r.post('/device/{device_id}/command')
    async def device_command(device_id:str,req:DeviceActionRequest,authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):
        auth(authorization,x_device_id,'device:read')
        action=str(req.action or '').strip()
        if action not in {'device_info','battery','voice_status'}:
            raise HTTPException(409,'Consequential device commands require canonical governed execution')
        cmd=DeviceCommand(action,dict(req.parameters or {}),str(uuid.uuid4()))
        try:return await runtime['device_gateway'].request(device_id,cmd,max(1,min(req.timeout,60)))
        except Exception as e:raise HTTPException(409,str(e))
    return r
