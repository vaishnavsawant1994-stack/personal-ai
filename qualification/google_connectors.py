from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib, json, re, time

_FORBIDDEN_KEYS=('token','authorization_code','client_secret','pkce','verifier','file_content','cell_content','raw_content','password')

def redact_account(value:str)->str:
    value=(value or '').strip().casefold()
    if not value:return ''
    if '@' in value:
        local,domain=value.split('@',1); return (local[:1]+'***@'+domain) if local else '***@'+domain
    return 'sha256:'+hashlib.sha256(value.encode()).hexdigest()[:16]

def _safe(value):
    if isinstance(value,dict):
        out={}
        for k,v in value.items():
            low=str(k).casefold()
            if any(x in low for x in _FORBIDDEN_KEYS):continue
            out[str(k)]=_safe(v)
        return out
    if isinstance(value,(list,tuple)):return [_safe(x) for x in value]
    if isinstance(value,str):
        if re.search(r'(?i)bearer\s+[a-z0-9._~-]{12,}',value):return '[REDACTED]'
        return value[:2000]
    return value

@dataclass(frozen=True)
class GoogleQualificationEvidence:
    git_sha:str
    deployment_id:str
    environment:str
    service:str
    google_account:str
    connector:str
    granted_scopes:list[str]
    owner_id:str
    device_id:str
    session_id:str
    security_epoch:int
    operation_id:str
    expected_result:str
    actual_result:str
    timestamp:float
    safe_logs:dict
    artifact_ref:str
    passed:bool
    evidence_kind:str='real_provider'

    def safe_record(self):
        data=asdict(self); data['google_account']=redact_account(self.google_account); data['safe_logs']=_safe(self.safe_logs)
        data['granted_scopes']=sorted(set(str(x) for x in self.granted_scopes))
        return data

class GoogleQualificationRecorder:
    def __init__(self,path:Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
    def append(self,evidence:GoogleQualificationEvidence):
        row=evidence.safe_record()
        forbidden=json.dumps(row,sort_keys=True).casefold()
        for key in ('access_token','refresh_token','authorization_code','client_secret','pkce_verifier','file_content','cell_content'):
            if key in forbidden: raise ValueError('unsafe qualification evidence field')
        with self.path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n')
        return row

def qualification_resource_names(stamp:int|None=None):
    stamp=int(time.time() if stamp is None else stamp)
    base=f'Personal AI Connector Qualification {stamp}'
    return {'drive_created':base+' Created.txt','drive_uploaded':base+' Uploaded.txt','spreadsheet':base}
