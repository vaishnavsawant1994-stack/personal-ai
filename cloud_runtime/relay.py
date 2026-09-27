from __future__ import annotations
import time
from collections import defaultdict,deque
from dataclasses import dataclass
from agent.executor import ConfirmationRequired
from cloud_runtime.security import CloudSessionStore,OwnerAuthenticator

@dataclass
class RelayResult:
    status:int
    payload:dict

class SlidingWindowLimiter:
    def __init__(self,limit:int=30,window_seconds:int=60):self.limit=max(1,limit);self.window=max(1,window_seconds);self._hits=defaultdict(deque)
    def allow(self,key:str)->bool:
        now=time.time();q=self._hits[key]
        while q and q[0] <= now-self.window:q.popleft()
        if len(q)>=self.limit:return False
        q.append(now);return True

class SecureCloudRelay:
    """Policy boundary between an internet-facing client and the privileged Personal AI runtime."""
    def __init__(self,*,executor,memory,second_brain,device_registry,sessions:CloudSessionStore,owner:OwnerAuthenticator,events=None):
        self.executor=executor;self.memory=memory;self.second_brain=second_brain;self.device_registry=device_registry;self.sessions=sessions;self.owner=owner;self.events=events;self.rate=SlidingWindowLimiter();self._state='idle'
        if events:events.subscribe('state',self._on_state)
    def _on_state(self,event):self._state=str(event.get('state','unknown'))
    def authenticate(self,token:str,scope:str,nonce:str|None=None):
        s=self.sessions.authenticate(token,scope)
        if not s:return RelayResult(401,{'error':'unauthorized'}),None
        if not self.device_registry or not self.device_registry.is_active(s.device_id):
            self.sessions.revoke(s.id);return RelayResult(401,{'error':'device_revoked'}),None
        if not self.rate.allow(s.id):return RelayResult(429,{'error':'rate_limited'}),None
        if nonce is not None and not self.sessions.accept_nonce(s.id,nonce):return RelayResult(409,{'error':'replay_detected'}),None
        return None,s
    def issue_session(self,device_id:str,device_token:str):
        if not self.device_registry or not self.device_registry.authenticate(device_id,device_token):return RelayResult(401,{'error':'device_auth_failed'})
        token,s=self.sessions.issue(device_id)
        self.memory.audit('cloud','session_issued',{'session_id':s.id,'device_id':device_id,'expires_at':s.expires_at})
        return RelayResult(200,{'session_token':token,'session_id':s.id,'expires_at':s.expires_at,'scopes':list(s.scopes)})
    def revoke_session(self,session_id:str,device_id:str):
        ok=self.sessions.revoke(session_id);self.memory.audit('cloud','session_revoked',{'session_id':session_id,'device_id':device_id,'ok':ok});return RelayResult(200,{'revoked':ok})
    def command(self,session,text:str,nonce:str):
        if self.sessions.emergency_stopped():return RelayResult(423,{'error':'emergency_stop_active'})
        text=(text or '').strip()
        if not text:return RelayResult(400,{'error':'empty_command'})
        if len(text)>12000:return RelayResult(413,{'error':'command_too_large'})
        try:
            reply=self.executor.chat(text);self.memory.audit('cloud','command',{'device_id':session.device_id,'ok':True});return RelayResult(200,{'reply':reply,'state':self._state})
        except ConfirmationRequired as exc:
            payload={'approval_required':True,'approval_id':exc.approval_id,'execution_id':exc.execution_id,'tool':exc.tool_name,'description':exc.description,'parameters':exc.parameters,'expires_at':exc.expires_at}
            self.memory.audit('cloud','approval_required',{'device_id':session.device_id,'approval_id':exc.approval_id,'tool':exc.tool_name});return RelayResult(202,payload)
    def memory_search(self,session,q:str,include_sensitive:bool=False):
        rows=self.memory.search((q or '').strip(),limit=20)
        allowed=[]
        for row in rows:
            sensitivity=str(row.get('sensitivity','normal')).lower()
            if sensitivity not in {'normal','public'} and not (include_sensitive and 'memory:sensitive' in session.scopes):continue
            allowed.append({k:row.get(k) for k in ('id','type','subject','content','source','confidence','verified','sensitivity','created_at','updated_at')})
        self.memory.audit('cloud','memory_search',{'device_id':session.device_id,'query_length':len(q or ''),'count':len(allowed)})
        return RelayResult(200,{'results':allowed})
    def status(self,session):
        return RelayResult(200,{'state':self._state,'emergency_stop':self.sessions.emergency_stopped(),'device_id':session.device_id})
    def approval(self,session,approval_id:str,decision:str):
        if self.sessions.emergency_stopped():return RelayResult(423,{'error':'emergency_stop_active'})
        try:
            if decision=='approve':reply=self.executor.approve(approval_id)
            elif decision=='reject':reply=self.executor.reject(approval_id)
            else:return RelayResult(400,{'error':'invalid_decision'})
            self.memory.audit('cloud','approval_decision',{'device_id':session.device_id,'approval_id':approval_id,'decision':decision});return RelayResult(200,{'reply':reply,'decision':decision})
        except PermissionError:return RelayResult(410,{'error':'approval_unavailable'})
    def set_emergency_stop(self,owner_secret:str,enabled:bool):
        if not self.owner.verify(owner_secret):return RelayResult(401,{'error':'owner_auth_failed'})
        self.sessions.set_emergency_stop(enabled)
        self.memory.audit('cloud','emergency_stop',{'enabled':enabled})
        if self.events:self.events.emit('emergency.stop',enabled=enabled)
        return RelayResult(200,{'emergency_stop':enabled})
