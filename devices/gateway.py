from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any
@dataclass
class DeviceCommand:
    action:str; parameters:dict[str,Any]; request_id:str
class DeviceGateway:
    def __init__(self,registry,events):self.registry=registry;self.events=events;self._sessions={};self._pending={}
    def connect(self,device_id,session):self._sessions[device_id]=session;self.events.emit('device.connected',device_id=device_id)
    def disconnect(self,device_id):self._sessions.pop(device_id,None);self.events.emit('device.disconnected',device_id=device_id)
    async def send(self,device_id,command:DeviceCommand):
        session=self._sessions.get(device_id)
        if session is None:raise RuntimeError('device is offline')
        await session.send_json({'type':'command','request_id':command.request_id,'action':command.action,'parameters':command.parameters});return {'queued':True,'request_id':command.request_id}
    async def request(self,device_id,command:DeviceCommand,timeout=15):
        loop=asyncio.get_running_loop(); fut=loop.create_future(); self._pending[command.request_id]=fut
        try:await self.send(device_id,command);return await asyncio.wait_for(fut,timeout)
        finally:self._pending.pop(command.request_id,None)
    def receive(self,device_id,msg:dict):
        rid=msg.get('request_id'); fut=self._pending.get(rid)
        if fut and not fut.done():fut.set_result({'device_id':device_id,**msg})
        self.events.emit('device.message',device_id=device_id,message=msg)
    def online(self):return sorted(self._sessions)
