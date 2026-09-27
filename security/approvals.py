from __future__ import annotations
from dataclasses import dataclass
import hashlib,json,secrets,threading,time
from typing import Any

def parameter_hash(parameters:dict[str,Any])->str:
    raw=json.dumps(parameters or {},sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class ApprovalTicket:
    id:str
    execution_id:str
    tool_name:str
    parameter_hash:str
    created_at:float
    expires_at:float

class ApprovalManager:
    """One-use approvals bound to one execution, one tool and one exact parameter hash."""
    def __init__(self,ttl_seconds:int=300):
        self.ttl_seconds=max(1,int(ttl_seconds));self._tickets={};self._lock=threading.RLock()
    def create(self,execution_id:str,tool_name:str,parameters:dict[str,Any])->ApprovalTicket:
        now=time.time();ticket=ApprovalTicket(secrets.token_urlsafe(24),execution_id,tool_name,parameter_hash(parameters),now,now+self.ttl_seconds)
        with self._lock:self._tickets[ticket.id]=ticket
        return ticket
    def consume(self,ticket_id:str,execution_id:str,tool_name:str,parameters:dict[str,Any],*,now:float|None=None)->ApprovalTicket:
        now=time.time() if now is None else float(now)
        with self._lock:
            ticket=self._tickets.pop(ticket_id,None)
        if not ticket:raise PermissionError('approval is missing, expired, rejected, or already used')
        if now>ticket.expires_at:raise PermissionError('approval expired')
        if ticket.execution_id!=execution_id or ticket.tool_name!=tool_name or ticket.parameter_hash!=parameter_hash(parameters):raise PermissionError('approval scope mismatch')
        return ticket
    def reject(self,ticket_id:str)->bool:
        with self._lock:return self._tickets.pop(ticket_id,None) is not None
    def purge_expired(self,*,now:float|None=None)->int:
        now=time.time() if now is None else float(now)
        with self._lock:
            stale=[k for k,v in self._tickets.items() if now>v.expires_at]
            for k in stale:self._tickets.pop(k,None)
        return len(stale)
