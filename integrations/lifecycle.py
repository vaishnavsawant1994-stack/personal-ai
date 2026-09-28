from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
from integrations.contracts import HEALTH_STATES
from security.action_audit import TrustedActionAudit,redact_audit_value
DROP_KEYS={'token','access_token','refresh_token','authorization_code','code','state','verifier','pkce_verifier','client_secret','secret','raw','body','content'}
class ConnectorLifecycleAudit:
    def __init__(self,data_dir):self.audit=TrustedActionAudit(Path(data_dir)/'trusted-action-audit.sqlite3')
    def append(self,event_type,*,connector_id=None,owner_id='owner',device_id=None,session_id=None,correlation_id=None,payload=None):
        safe={k:v for k,v in dict(payload or {}).items() if str(k).lower() not in DROP_KEYS}
        return self.audit.append('connector',str(event_type),redact_audit_value({'connector_id':connector_id,'owner_id':owner_id,'device_id':device_id,'session_id':session_id,'correlation_id':correlation_id,**safe}))
    def entries(self,limit=200):return [x for x in self.audit.entries(limit) if x.get('category')=='connector']
    def verify(self):return self.audit.verify_chain()
class ConnectorHealthStore:
    def __init__(self,path,audit):self.path=Path(path);self.audit=audit
    def _con(self):c=sqlite3.connect(self.path,timeout=30,isolation_level=None);c.row_factory=sqlite3.Row;c.execute('PRAGMA busy_timeout=30000');return c
    def set(self,connector_id,state,*,scopes=None,error_code=None,error_message=None,success=False,revocation_status=None):
        if state not in HEALTH_STATES:raise ValueError('invalid connector health state')
        stamp=time.time();scopes_json=json.dumps(sorted(set(scopes or [])),separators=(',',':'))
        with self._con() as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM connector_health WHERE connector_id=?',(connector_id,)).fetchone();last=stamp if success else (old['last_success_at'] if old else None);rev=revocation_status if revocation_status is not None else (old['revocation_status'] if old else 'none')
            if scopes is None and old:scopes_json=old['granted_scopes_json']
            old_state=old['state'] if old else None
            c.execute('''INSERT INTO connector_health(connector_id,state,granted_scopes_json,last_success_at,last_checked_at,last_error_code,last_error_message,revocation_status,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(connector_id) DO UPDATE SET state=excluded.state,granted_scopes_json=excluded.granted_scopes_json,last_success_at=excluded.last_success_at,last_checked_at=excluded.last_checked_at,last_error_code=excluded.last_error_code,last_error_message=excluded.last_error_message,revocation_status=excluded.revocation_status,updated_at=excluded.updated_at''',(connector_id,state,scopes_json,last,stamp,error_code,str(error_message or '')[:240] or None,rev,stamp));c.commit()
        if old_state and old_state!=state:self.audit.append('connector.reconnected' if state=='healthy' else 'connector.degraded',connector_id=connector_id,payload={'from':old_state,'to':state,'error_code':error_code})
    def get(self,connector_id):
        with self._con() as c:r=c.execute('SELECT * FROM connector_health WHERE connector_id=?',(connector_id,)).fetchone()
        if not r:return {'connector_id':connector_id,'state':'disconnected','granted_scopes':[],'last_success_at':None,'last_checked_at':None,'last_error_code':None,'last_error_message':None,'revocation_status':'none'}
        d=dict(r);d['granted_scopes']=json.loads(d.pop('granted_scopes_json') or '[]');return d
