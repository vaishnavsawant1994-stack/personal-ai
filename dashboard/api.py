from __future__ import annotations
from fastapi import APIRouter,HTTPException,Header
from pydantic import BaseModel,Field
import uuid
from devices.gateway import DeviceCommand
class ActionRequest(BaseModel):tool:str;parameters:dict=Field(default_factory=dict)
class DeviceActionRequest(BaseModel):action:str;parameters:dict=Field(default_factory=dict);timeout:float=15

def dashboard_router(runtime,auth_device):
    r=APIRouter(prefix='/dashboard',tags=['dashboard'])
    def auth(a,d):auth_device(a,d)
    @r.get('/status')
    def status(authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):
        auth(authorization,x_device_id); return {'automations':len(runtime['automations'].list()),'devices':len(runtime['device_registry'].list()),'online_devices':runtime['device_gateway'].online(),'integrations':runtime.get('integrations').list() if runtime.get('integrations') else [],'memory_nodes':len(runtime['second_brain'].graph().get('nodes',[])),'voice_state':'active' if getattr(runtime.get('voice'),'thread',None) and runtime['voice'].thread.is_alive() else 'idle','security':{'vault':'keychain-backed' if runtime.get('vault') else 'unavailable','autonomy':runtime['tools'].settings.autonomy_mode}}
    @r.get('/devices')
    def devices(authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):auth(authorization,x_device_id);return runtime['device_registry'].list()
    @r.get('/automations')
    def automations(authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):auth(authorization,x_device_id);return runtime['automations'].list()
    @r.get('/memory')
    def memory(authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):auth(authorization,x_device_id);return runtime['second_brain'].graph()
    @r.post('/tool')
    def tool(req:ActionRequest,authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):
        auth(authorization,x_device_id)
        try:t=runtime['tools'].get(req.tool)
        except Exception:raise HTTPException(404,'unknown tool')
        if not runtime['tools'].automatic(t):raise HTTPException(409,'tool requires interactive confirmation')
        return {'result':t.handler(req.parameters)}
    @r.post('/device/{device_id}/command')
    async def device_command(device_id:str,req:DeviceActionRequest,authorization:str|None=Header(default=None),x_device_id:str|None=Header(default=None)):
        auth(authorization,x_device_id);cmd=DeviceCommand(req.action,req.parameters,str(uuid.uuid4()))
        try:return await runtime['device_gateway'].request(device_id,cmd,max(1,min(req.timeout,60)))
        except Exception as e:raise HTTPException(409,str(e))
    return r
