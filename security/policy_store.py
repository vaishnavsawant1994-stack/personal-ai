from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

SCHEMA_VERSION = 73

def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)

def digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()

def ensure_policy_schema(con: sqlite3.Connection) -> None:
    con.execute('''CREATE TABLE IF NOT EXISTS operator_policies(
        policy_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,device_id TEXT,session_id TEXT,scope TEXT NOT NULL,
        target_type TEXT NOT NULL,target_json TEXT NOT NULL,allowed_ops_json TEXT NOT NULL,denied_ops_json TEXT NOT NULL,
        sensitivity_json TEXT NOT NULL,approval_rule TEXT NOT NULL,reauth_rule TEXT NOT NULL,priority INTEGER NOT NULL,
        valid_from REAL NOT NULL,expires_at REAL,version INTEGER NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
        actor TEXT NOT NULL,security_epoch INTEGER NOT NULL,active INTEGER NOT NULL,revoked_at REAL,max_uses INTEGER,use_count INTEGER NOT NULL DEFAULT 0)''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_operator_policies_effective ON operator_policies(owner_id,target_type,active,priority,updated_at)')
    con.execute('''CREATE TABLE IF NOT EXISTS operator_policy_permits(
        permit_id TEXT PRIMARY KEY,policy_digest TEXT NOT NULL,binding_digest TEXT NOT NULL,owner_id TEXT NOT NULL,
        device_id TEXT,session_id TEXT,security_epoch INTEGER NOT NULL,operation TEXT NOT NULL,expires_at REAL NOT NULL,
        uses_remaining INTEGER NOT NULL,created_at REAL NOT NULL,status TEXT NOT NULL,recovery_reason TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS operator_policy_audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT,created_at REAL NOT NULL,event TEXT NOT NULL,owner_id TEXT,policy_id TEXT,
        version INTEGER,decision TEXT,reason_code TEXT,target_digest TEXT,operation TEXT,policy_digest TEXT,details_json TEXT NOT NULL)''')
    current=int(con.execute('PRAGMA user_version').fetchone()[0])
    if current<SCHEMA_VERSION:con.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

class PolicyStore:
    def __init__(self,path:str|Path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self._lock=threading.RLock()
        with self._con() as con:ensure_policy_schema(con)
    def _con(self):
        con=sqlite3.connect(self.path,timeout=30);con.row_factory=sqlite3.Row;return con
    def schema_version(self)->int:
        with self._con() as con:ensure_policy_schema(con);return int(con.execute('PRAGMA user_version').fetchone()[0])
    def upsert_policy(self,*,owner_id:str,target_type:str,target_identity:dict,allowed_operations=(),denied_operations=(),sensitivity_restrictions=(),approval_rule:str='none',reauth_rule:str='none',priority:int=100,valid_from:float|None=None,expires_at:float|None=None,actor:str='owner',security_epoch:int=0,device_id:str|None=None,session_id:str|None=None,scope:str='owner',active:bool=True,max_uses:int|None=None,policy_id:str|None=None,reauthenticated:bool=False)->dict:
        if not reauthenticated:raise PermissionError('reauthentication_required')
        now=time.time();pid=str(policy_id or uuid.uuid4())
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');existing=con.execute('SELECT version,created_at FROM operator_policies WHERE policy_id=?',(pid,)).fetchone();version=int(existing['version'])+1 if existing else 1;created=float(existing['created_at']) if existing else now
            row=(pid,str(owner_id),device_id,session_id,str(scope),str(target_type),canonical_json(target_identity),canonical_json(sorted(set(map(str,allowed_operations)))),canonical_json(sorted(set(map(str,denied_operations)))),canonical_json(sorted(set(map(str,sensitivity_restrictions)))),str(approval_rule),str(reauth_rule),int(priority),float(valid_from if valid_from is not None else now),float(expires_at) if expires_at is not None else None,version,created,now,str(actor),int(security_epoch),1 if active else 0,None,int(max_uses) if max_uses is not None else None,0)
            con.execute('''INSERT INTO operator_policies(policy_id,owner_id,device_id,session_id,scope,target_type,target_json,allowed_ops_json,denied_ops_json,sensitivity_json,approval_rule,reauth_rule,priority,valid_from,expires_at,version,created_at,updated_at,actor,security_epoch,active,revoked_at,max_uses,use_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(policy_id) DO UPDATE SET owner_id=excluded.owner_id,device_id=excluded.device_id,session_id=excluded.session_id,scope=excluded.scope,target_type=excluded.target_type,target_json=excluded.target_json,allowed_ops_json=excluded.allowed_ops_json,denied_ops_json=excluded.denied_ops_json,sensitivity_json=excluded.sensitivity_json,approval_rule=excluded.approval_rule,reauth_rule=excluded.reauth_rule,priority=excluded.priority,valid_from=excluded.valid_from,expires_at=excluded.expires_at,version=excluded.version,updated_at=excluded.updated_at,actor=excluded.actor,security_epoch=excluded.security_epoch,active=excluded.active,revoked_at=NULL,max_uses=excluded.max_uses,use_count=0''',row)
            self._audit_con(con,'policy_upserted',owner_id=str(owner_id),policy_id=pid,version=version,details={'target_type':target_type,'actor':actor,'active':bool(active)});con.commit()
        return self.get(pid)
    def revoke_policy(self,policy_id:str,*,owner_id:str,actor:str='owner',reauthenticated:bool=False)->bool:
        if not reauthenticated:raise PermissionError('reauthentication_required')
        now=time.time()
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');row=con.execute('SELECT * FROM operator_policies WHERE policy_id=? AND owner_id=?',(policy_id,owner_id)).fetchone()
            if not row:con.rollback();return False
            version=int(row['version'])+1;con.execute('UPDATE operator_policies SET active=0,revoked_at=?,updated_at=?,version=?,actor=? WHERE policy_id=?',(now,now,version,actor,policy_id));self._audit_con(con,'policy_revoked',owner_id=owner_id,policy_id=policy_id,version=version,details={'actor':actor});con.commit();return True
    def set_policy_active(self,policy_id:str,*,owner_id:str,enabled:bool,actor:str='owner',reauthenticated:bool=False)->bool:
        if not reauthenticated:raise PermissionError('reauthentication_required')
        now=time.time()
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');row=con.execute('SELECT version FROM operator_policies WHERE policy_id=? AND owner_id=?',(policy_id,owner_id)).fetchone()
            if not row:con.rollback();return False
            con.execute('UPDATE operator_policies SET active=?,revoked_at=?,updated_at=?,version=version+1,actor=? WHERE policy_id=?',(1 if enabled else 0,None if enabled else now,now,actor,policy_id));self._audit_con(con,'policy_enabled' if enabled else 'policy_disabled',owner_id=owner_id,policy_id=policy_id,version=int(row['version'])+1,details={'actor':actor});con.commit();return True
    def reset_owner(self,owner_id:str,*,actor:str='owner',reauthenticated:bool=False)->int:
        if not reauthenticated:raise PermissionError('reauthentication_required')
        now=time.time()
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');rows=con.execute('SELECT policy_id FROM operator_policies WHERE owner_id=? AND active=1',(owner_id,)).fetchall()
            for row in rows:con.execute('UPDATE operator_policies SET active=0,revoked_at=?,updated_at=?,version=version+1,actor=? WHERE policy_id=?',(now,now,actor,row['policy_id']))
            con.execute("UPDATE operator_policy_permits SET status='revoked',uses_remaining=0 WHERE owner_id=? AND status='active'",(owner_id,));self._audit_con(con,'safe_defaults_restored',owner_id=owner_id,details={'actor':actor,'revoked_count':len(rows)});con.commit();return len(rows)
    def get(self,policy_id:str)->dict|None:
        with self._con() as con:row=con.execute('SELECT * FROM operator_policies WHERE policy_id=?',(policy_id,)).fetchone()
        return self._decode_policy(row) if row else None
    def list_policies(self,owner_id:str,*,include_inactive:bool=False)->list[dict]:
        query='SELECT * FROM operator_policies WHERE owner_id=?';args=[owner_id]
        if not include_inactive:query+=' AND active=1'
        query+=' ORDER BY priority DESC,updated_at DESC,policy_id'
        with self._con() as con:rows=con.execute(query,args).fetchall()
        return [self._decode_policy(row) for row in rows]
    def effective_policies(self,owner_id:str,*,device_id:str|None,session_id:str|None,security_epoch:int,now:float|None=None)->list[dict]:
        ts=time.time() if now is None else float(now);result=[]
        for row in self.list_policies(owner_id):
            if row['security_epoch']!=int(security_epoch):continue
            if row['device_id'] is not None and row['device_id']!=device_id:continue
            if row['session_id'] is not None and row['session_id']!=session_id:continue
            if row['valid_from']>ts or (row['expires_at'] is not None and row['expires_at']<=ts):continue
            if row['max_uses'] is not None and row['use_count']>=row['max_uses']:continue
            result.append(row)
        return result
    @staticmethod
    def snapshot_digest(policies:list[dict])->str:
        snapshot=[{k:row[k] for k in ('policy_id','version','target_type','target_identity','allowed_operations','denied_operations','sensitivity_restrictions','approval_rule','reauth_rule','priority','expires_at','security_epoch','max_uses','use_count')} for row in policies]
        return digest(snapshot)
    def increment_use(self,policy_ids:list[str])->None:
        if not policy_ids:return
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            for pid in policy_ids:con.execute('UPDATE operator_policies SET use_count=use_count+1 WHERE policy_id=? AND active=1',(pid,))
            con.commit()
    def issue_permit(self,*,policy_digest:str,binding:dict,owner_id:str,device_id:str|None,session_id:str|None,security_epoch:int,operation:str,ttl_seconds:int=120,max_uses:int=1)->dict:
        permit_id=str(uuid.uuid4());now=time.time();expires=now+max(1,min(int(ttl_seconds),600));binding_digest=digest(binding);uses=max(1,min(int(max_uses),10))
        with self._lock,self._con() as con:
            con.execute('INSERT INTO operator_policy_permits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(permit_id,policy_digest,binding_digest,owner_id,device_id,session_id,int(security_epoch),operation,expires,uses,now,'active',None));self._audit_con(con,'permit_issued',owner_id=owner_id,decision='allow',reason_code='temporary_permit_issued',operation=operation,policy_digest=policy_digest,target_digest=binding.get('target_digest'),details={'permit_id':permit_id,'max_uses':uses,'expires_at':expires})
        return {'permit_id':permit_id,'expires_at':expires,'uses_remaining':uses,'binding_digest':binding_digest}
    def consume_permit(self,permit_id:str,*,binding:dict,owner_id:str,device_id:str|None,session_id:str|None,security_epoch:int,policy_digest:str)->bool:
        now=time.time();expected=digest(binding)
        with self._lock,self._con() as con:
            con.execute('BEGIN IMMEDIATE');row=con.execute('SELECT * FROM operator_policy_permits WHERE permit_id=?',(permit_id,)).fetchone()
            if not row or row['status']!='active' or row['expires_at']<=now or row['uses_remaining']<=0:con.rollback();return False
            if row['owner_id']!=owner_id or row['device_id']!=device_id or row['session_id']!=session_id or int(row['security_epoch'])!=int(security_epoch):con.rollback();return False
            if row['policy_digest']!=policy_digest or row['binding_digest']!=expected:con.rollback();return False
            remaining=int(row['uses_remaining'])-1;status='used' if remaining==0 else 'active';con.execute('UPDATE operator_policy_permits SET uses_remaining=?,status=? WHERE permit_id=?',(remaining,status,permit_id));con.commit();return True
    def mark_recovery_review(self,permit_id:str,reason:str='unknown_outcome')->None:
        with self._lock,self._con() as con:con.execute("UPDATE operator_policy_permits SET status='recovery_review_required',uses_remaining=0,recovery_reason=? WHERE permit_id=?",(str(reason)[:200],permit_id))
    def audit_decision(self,*,event:str='policy_decision',owner_id:str|None=None,policy_id:str|None=None,version:int|None=None,decision:str|None=None,reason_code:str|None=None,target_digest:str|None=None,operation:str|None=None,policy_digest:str|None=None,details:dict|None=None)->None:
        with self._con() as con:self._audit_con(con,event,owner_id=owner_id,policy_id=policy_id,version=version,decision=decision,reason_code=reason_code,target_digest=target_digest,operation=operation,policy_digest=policy_digest,details=details or {})
    def recent_audit(self,owner_id:str,limit:int=50)->list[dict]:
        with self._con() as con:rows=con.execute('SELECT * FROM operator_policy_audit WHERE owner_id=? ORDER BY id DESC LIMIT ?',(owner_id,max(1,min(int(limit),200)))).fetchall()
        return [dict(row) for row in rows]
    @staticmethod
    def _audit_con(con,event:str,**values)->None:
        details=dict(values.pop('details',{}) or {});safe_details={k:v for k,v in details.items() if k not in {'content','clipboard','password','secret','token','authorization','cookie','parameters'}}
        con.execute('''INSERT INTO operator_policy_audit(created_at,event,owner_id,policy_id,version,decision,reason_code,target_digest,operation,policy_digest,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(time.time(),event,values.get('owner_id'),values.get('policy_id'),values.get('version'),values.get('decision'),values.get('reason_code'),values.get('target_digest'),values.get('operation'),values.get('policy_digest'),canonical_json(safe_details)))
    @staticmethod
    def _decode_policy(row)->dict:
        data=dict(row)
        for source,dest in (('target_json','target_identity'),('allowed_ops_json','allowed_operations'),('denied_ops_json','denied_operations'),('sensitivity_json','sensitivity_restrictions')):data[dest]=json.loads(data.pop(source))
        data['active']=bool(data['active']);return data
