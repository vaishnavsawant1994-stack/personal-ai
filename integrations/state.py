from __future__ import annotations

import hashlib, json, sqlite3, time, uuid
from pathlib import Path
from typing import Any
from integrations.lifecycle import ConnectorLifecycleAudit,ConnectorHealthStore

OAUTH_TERMINAL={'consumed','expired','invalidated','failed'}
OPERATION_STATES={'proposed','approved','dispatched','confirmed','verification_pending','verified','failed','outcome_unknown','recovery_review_required','rolled_back','rollback_failed'}


def _json(value): return json.dumps(value,sort_keys=True,separators=(',',':'),default=str)
def _hash_text(value: str): return hashlib.sha256(str(value).encode()).hexdigest()
def _now(): return time.time()

class ConnectorStateStore:
    def __init__(self,path:Path,*,vault=None):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.vault=vault; self.lifecycle=ConnectorLifecycleAudit(self.path.parent); self._init(); self.health_store=ConnectorHealthStore(self.path,self.lifecycle)
    def _con(self):
        con=sqlite3.connect(self.path,timeout=30,isolation_level=None); con.row_factory=sqlite3.Row; con.execute('PRAGMA busy_timeout=30000'); return con
    def _init(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS connector_health(
              connector_id TEXT PRIMARY KEY,state TEXT NOT NULL DEFAULT 'disconnected',granted_scopes_json TEXT NOT NULL DEFAULT '[]',
              last_success_at REAL,last_checked_at REAL,last_error_code TEXT,last_error_message TEXT,revocation_status TEXT NOT NULL DEFAULT 'none',updated_at REAL NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS oauth_transactions(
              state_digest TEXT PRIMARY KEY,owner_id TEXT NOT NULL,device_id TEXT,session_id TEXT,connector_id TEXT NOT NULL,provider_id TEXT NOT NULL,
              scopes_json TEXT NOT NULL,challenge TEXT NOT NULL,nonce_digest TEXT,redirect_uri TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL,
              consumed_at REAL,security_epoch INTEGER NOT NULL,relink_intent TEXT NOT NULL DEFAULT 'connect',status TEXT NOT NULL DEFAULT 'pending',failure_code TEXT)""",
            "CREATE INDEX IF NOT EXISTS idx_oauth_binding ON oauth_transactions(device_id,session_id,status,expires_at)",
            """CREATE TABLE IF NOT EXISTS connector_operations(
              operation_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,device_id TEXT,session_id TEXT,connector_id TEXT NOT NULL,operation_name TEXT NOT NULL,
              parameter_hash TEXT NOT NULL,destination TEXT NOT NULL DEFAULT '',idempotency_key TEXT NOT NULL UNIQUE,provider_account TEXT NOT NULL DEFAULT '',content_checksum TEXT NOT NULL DEFAULT '',provider_request_id TEXT,provider_resource_id TEXT,
              dispatch_time REAL,state TEXT NOT NULL,verification_state TEXT NOT NULL DEFAULT 'not_started',verification_evidence_json TEXT NOT NULL DEFAULT '{}',rollback_available INTEGER NOT NULL DEFAULT 0,
              retry_decision TEXT NOT NULL DEFAULT '',result_json TEXT NOT NULL DEFAULT '{}',created_at REAL NOT NULL,updated_at REAL NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_connector_operations_lookup ON connector_operations(connector_id,operation_name,created_at)",
        ]
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                for statement in statements: con.execute(statement)
                cols={r['name'] for r in con.execute('PRAGMA table_info(connector_health)')}
                additions={'revocation_status':"TEXT NOT NULL DEFAULT 'none'",'last_error_code':'TEXT','last_error_message':'TEXT'}
                for name,definition in additions.items():
                    if name not in cols: con.execute(f'ALTER TABLE connector_health ADD COLUMN {name} {definition}')
                opcols={r['name'] for r in con.execute('PRAGMA table_info(connector_operations)')}
                opadd={'provider_account':"TEXT NOT NULL DEFAULT ''",'content_checksum':"TEXT NOT NULL DEFAULT ''",'verification_evidence_json':"TEXT NOT NULL DEFAULT '{}'"}
                for name,definition in opadd.items():
                    if name not in opcols: con.execute(f'ALTER TABLE connector_operations ADD COLUMN {name} {definition}')
                con.commit()
            except Exception:
                con.rollback()
                raise
    def audit(self,event_type,*,connector_id=None,owner_id='owner',device_id=None,session_id=None,correlation_id=None,payload=None):
        return self.lifecycle.append(event_type,connector_id=connector_id,owner_id=owner_id,device_id=device_id,session_id=session_id,correlation_id=correlation_id,payload=payload)
    def verify_audit_chain(self):return bool(self.lifecycle.verify().get('ok'))
    def set_health(self,connector_id,state,**kwargs):return self.health_store.set(connector_id,state,**kwargs)
    def health(self,connector_id):return self.health_store.get(connector_id)
    def create_oauth(self,*,state,verifier,owner_id,device_id,session_id,connector_id,provider_id,scopes,challenge,nonce,redirect_uri,security_epoch,relink_intent='connect',ttl_seconds=600):
        digest=_hash_text(state); stamp=_now(); expires=stamp+max(60,min(int(ttl_seconds),1800)); nonce_digest=_hash_text(nonce) if nonce else None
        if not self.vault: raise RuntimeError('encrypted vault is required for durable OAuth transactions')
        self.vault.set('oauth-txn:'+digest,verifier)
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); con.execute('''INSERT INTO oauth_transactions(state_digest,owner_id,device_id,session_id,connector_id,provider_id,scopes_json,challenge,nonce_digest,redirect_uri,created_at,expires_at,consumed_at,security_epoch,relink_intent,status,failure_code)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,"pending",NULL)''',(digest,owner_id,device_id,session_id,connector_id,provider_id,_json(sorted(set(scopes))),challenge,nonce_digest,redirect_uri,stamp,expires,int(security_epoch),relink_intent)); con.commit()
        self.audit('oauth.started',connector_id=connector_id,owner_id=owner_id,device_id=device_id,session_id=session_id,correlation_id=digest[:16],payload={'provider':provider_id,'scopes':sorted(set(scopes)),'intent':relink_intent})
        return digest
    def consume_oauth(self,*,state,owner_id,device_id,session_id,connector_id,provider_id,security_epoch,now=None):
        stamp=_now() if now is None else float(now); digest=_hash_text(state)
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT * FROM oauth_transactions WHERE state_digest=?',(digest,)).fetchone()
            if not row: con.rollback(); raise PermissionError('OAuth transaction is invalid or already consumed')
            if row['status']!='pending': con.rollback(); self.audit('oauth.replay_rejected',connector_id=row['connector_id'],owner_id=owner_id,device_id=device_id,session_id=session_id,correlation_id=digest[:16],payload={'status':row['status']}); raise PermissionError('OAuth transaction is invalid or already consumed')
            if stamp>float(row['expires_at']):
                con.execute("UPDATE oauth_transactions SET status='expired',failure_code='expired' WHERE state_digest=?",(digest,)); con.commit(); self._delete_verifier(digest); raise PermissionError('OAuth transaction expired')
            checks=[('owner',row['owner_id'],owner_id),('device',row['device_id'],device_id),('session',row['session_id'],session_id),('connector',row['connector_id'],connector_id),('provider',row['provider_id'],provider_id),('security epoch',str(row['security_epoch']),str(int(security_epoch)))]
            mismatch=next((name for name,a,b in checks if (a or None)!=(b or None)),None)
            if mismatch: con.rollback(); raise PermissionError(f'OAuth {mismatch} mismatch')
            cur=con.execute("UPDATE oauth_transactions SET status='consumed',consumed_at=? WHERE state_digest=? AND status='pending'",(stamp,digest))
            if cur.rowcount!=1: con.rollback(); raise PermissionError('OAuth transaction is invalid or already consumed')
            con.commit()
        verifier=self.vault.get('oauth-txn:'+digest) if self.vault else None
        self._delete_verifier(digest)
        if not verifier: raise PermissionError('OAuth verifier unavailable')
        data=dict(row); data['scopes']=json.loads(data.pop('scopes_json')); data['verifier']=verifier; return data
    def fail_oauth(self,state_digest,code):
        with self._con() as con: con.execute("UPDATE oauth_transactions SET status='failed',failure_code=? WHERE state_digest=? AND status='pending'",(str(code)[:80],state_digest))
        self._delete_verifier(state_digest)
    def invalidate_device(self,device_id): return self._invalidate('device_id',device_id)
    def invalidate_session(self,session_id): return self._invalidate('session_id',session_id)
    def _invalidate(self,column,value):
        if column not in {'device_id','session_id'}: raise ValueError('invalid OAuth invalidation scope')
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); rows=con.execute(f"SELECT state_digest FROM oauth_transactions WHERE {column}=? AND status='pending'",(str(value),)).fetchall(); con.execute(f"UPDATE oauth_transactions SET status='invalidated',failure_code='trust_revoked' WHERE {column}=? AND status='pending'",(str(value),)); con.commit()
        for row in rows:self._delete_verifier(row['state_digest'])
        return len(rows)
    def _delete_verifier(self,digest):
        if self.vault:
            try:self.vault.delete('oauth-txn:'+digest)
            except Exception:pass
    def propose_operation(self,*,owner_id='owner',device_id=None,session_id=None,connector_id,operation_name,parameter_hash,destination='',idempotency_key=None,rollback_available=False,provider_account='',content_checksum=''):
        key=idempotency_key or str(uuid.uuid4())
        stamp=_now(); opid=str(uuid.uuid4())
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); existing=con.execute('SELECT * FROM connector_operations WHERE idempotency_key=?',(key,)).fetchone()
            if existing: con.rollback(); return self._decode_operation(existing),False
            con.execute("""INSERT INTO connector_operations(operation_id,owner_id,device_id,session_id,connector_id,operation_name,parameter_hash,destination,idempotency_key,provider_account,content_checksum,provider_request_id,provider_resource_id,dispatch_time,state,verification_state,verification_evidence_json,rollback_available,retry_decision,result_json,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,'proposed','not_started','{}',?,'','{}',?,?)""",(opid,owner_id,device_id,session_id,connector_id,operation_name,parameter_hash,destination,key,str(provider_account or '')[:500],str(content_checksum or '')[:200],int(bool(rollback_available)),stamp,stamp)); con.commit()
        self.audit('operation.proposed',connector_id=connector_id,owner_id=owner_id,device_id=device_id,session_id=session_id,correlation_id=opid,payload={'operation':operation_name,'destination':destination,'provider_account':str(provider_account or '')[:200],'content_checksum':str(content_checksum or '')[:100]})
        return self.operation(opid),True

    def transition_operation(self,operation_id,state,*,verification_state=None,verification_evidence=None,provider_request_id=None,provider_resource_id=None,retry_decision=None,result=None):
        if state not in OPERATION_STATES: raise ValueError('invalid connector operation state')
        stamp=_now(); fields=['state=?','updated_at=?']; vals=[state,stamp]
        if state=='dispatched': fields+=['dispatch_time=?']; vals+=[stamp]
        for name,val in [('verification_state',verification_state),('provider_request_id',provider_request_id),('provider_resource_id',provider_resource_id),('retry_decision',retry_decision)]:
            if val is not None: fields.append(name+'=?'); vals.append(str(val)[:500])
        if verification_evidence is not None: fields.append('verification_evidence_json=?'); vals.append(_json(verification_evidence))
        if result is not None: fields.append('result_json=?'); vals.append(_json(result))
        vals.append(operation_id)
        with self._con() as con: con.execute('BEGIN IMMEDIATE'); cur=con.execute('UPDATE connector_operations SET '+','.join(fields)+' WHERE operation_id=?',vals); con.commit()
        if cur.rowcount!=1: raise KeyError(operation_id)
        return self.operation(operation_id)
    @staticmethod
    def _decode_operation(row):
        d=dict(row); d['result']=json.loads(d.pop('result_json') or '{}'); d['verification_evidence']=json.loads(d.pop('verification_evidence_json','{}') or '{}'); return d
    def operation(self,operation_id):
        with self._con() as con: row=con.execute('SELECT * FROM connector_operations WHERE operation_id=?',(operation_id,)).fetchone()
        if not row: raise KeyError(operation_id)
        return self._decode_operation(row)
    def by_idempotency(self,key):
        with self._con() as con: row=con.execute('SELECT * FROM connector_operations WHERE idempotency_key=?',(key,)).fetchone()
        return self._decode_operation(row) if row else None
    def recovery_required(self,connector_id=None):
        q="SELECT * FROM connector_operations WHERE state IN ('outcome_unknown','recovery_review_required','verification_pending','verification_failed')";args=[]
        if connector_id:q+=' AND connector_id=?';args.append(connector_id)
        q+=' ORDER BY created_at ASC'
        with self._con() as con: rows=con.execute(q,args).fetchall()
        return [self._decode_operation(r) for r in rows]




def invalidate_device_transactions(path:Path,device_id:str):
    p=Path(path)
    if not p.exists():return 0
    try:return ConnectorStateStore(p).invalidate_device(device_id)
    except Exception:return 0

def invalidate_session_transactions(path:Path,session_id:str):
    p=Path(path)
    if not p.exists():return 0
    try:return ConnectorStateStore(p).invalidate_session(session_id)
    except Exception:return 0
