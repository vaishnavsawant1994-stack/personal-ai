from __future__ import annotations
import hashlib,secrets,sqlite3,time,uuid
from dataclasses import dataclass
from pathlib import Path
@dataclass(frozen=True)
class PwaSession:
    id:str; device_id:str; created_at:float; last_seen_at:float; expires_at:float; reauthenticated_at:float|None
class PwaSessionStore:
    def __init__(self,path:Path,*,ttl_seconds:int=60*60*24*30):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.ttl_seconds=max(300,min(int(ttl_seconds),60*60*24*365))
        with self._con() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS pwa_sessions(id TEXT PRIMARY KEY,device_id TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,created_at REAL NOT NULL,last_seen_at REAL NOT NULL,expires_at REAL NOT NULL,reauthenticated_at REAL,revoked_at REAL)''');con.execute('CREATE INDEX IF NOT EXISTS idx_pwa_sessions_device ON pwa_sessions(device_id,revoked_at)')
    def _con(self):con=sqlite3.connect(self.path,timeout=30);con.row_factory=sqlite3.Row;return con
    @staticmethod
    def _hash(token):return hashlib.sha256(str(token).encode()).hexdigest()
    @staticmethod
    def _row(row):return PwaSession(row['id'],row['device_id'],float(row['created_at']),float(row['last_seen_at']),float(row['expires_at']),float(row['reauthenticated_at']) if row['reauthenticated_at'] is not None else None)
    def _invalidate_connector_session(self,session_id):
        try:
            from integrations.state import invalidate_session_transactions
            invalidate_session_transactions(self.path.parent/'connectors.sqlite3',str(session_id))
        except Exception:pass
    def issue(self,device_id,*,reauthenticated=True):
        now=time.time();token=secrets.token_urlsafe(32);sid=str(uuid.uuid4());reauth=now if reauthenticated else None;expires=now+self.ttl_seconds
        with self._con() as con:con.execute('INSERT INTO pwa_sessions VALUES(?,?,?,?,?,?,?,NULL)',(sid,str(device_id),self._hash(token),now,now,expires,reauth))
        return token,PwaSession(sid,str(device_id),now,now,expires,reauth)
    def authenticate(self,token,device_id,*,touch=True):
        if not token or not device_id:return None
        now=time.time();h=self._hash(token)
        with self._con() as con:
            row=con.execute('SELECT * FROM pwa_sessions WHERE token_hash=? AND device_id=? AND revoked_at IS NULL AND expires_at>=?',(h,str(device_id),now)).fetchone()
            if not row:return None
            if touch:con.execute('UPDATE pwa_sessions SET last_seen_at=? WHERE id=?',(now,row['id']));d=dict(row);d['last_seen_at']=now;return self._row(d)
        return self._row(row)
    def get(self,session_id):
        with self._con() as con:row=con.execute('SELECT * FROM pwa_sessions WHERE id=? AND revoked_at IS NULL AND expires_at>=?',(str(session_id),time.time())).fetchone()
        return self._row(row) if row else None
    def mark_reauthenticated(self,session_id,*,at=None):
        stamp=time.time() if at is None else float(at)
        with self._con() as con:cur=con.execute('UPDATE pwa_sessions SET reauthenticated_at=? WHERE id=? AND revoked_at IS NULL AND expires_at>=?',(stamp,str(session_id),time.time()))
        return cur.rowcount==1
    def revoke(self,session_id):
        with self._con() as con:cur=con.execute('UPDATE pwa_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL',(time.time(),str(session_id)))
        if cur.rowcount:self._invalidate_connector_session(session_id)
        return cur.rowcount==1
    def revoke_token(self,token):
        if not token:return False
        with self._con() as con:
            row=con.execute('SELECT id FROM pwa_sessions WHERE token_hash=? AND revoked_at IS NULL',(self._hash(token),)).fetchone();cur=con.execute('UPDATE pwa_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL',(time.time(),self._hash(token)))
        if row:self._invalidate_connector_session(row['id'])
        return cur.rowcount==1
    def revoke_device(self,device_id):
        with self._con() as con:
            rows=con.execute('SELECT id FROM pwa_sessions WHERE device_id=? AND revoked_at IS NULL',(str(device_id),)).fetchall();cur=con.execute('UPDATE pwa_sessions SET revoked_at=? WHERE device_id=? AND revoked_at IS NULL',(time.time(),str(device_id)))
        for row in rows:self._invalidate_connector_session(row['id'])
        return int(cur.rowcount)
    def revoke_all(self):
        with self._con() as con:rows=con.execute('SELECT id FROM pwa_sessions WHERE revoked_at IS NULL').fetchall();cur=con.execute('UPDATE pwa_sessions SET revoked_at=? WHERE revoked_at IS NULL',(time.time(),))
        for row in rows:self._invalidate_connector_session(row['id'])
        return int(cur.rowcount)
    def active_for_device(self,device_id):
        with self._con() as con:rows=con.execute('SELECT * FROM pwa_sessions WHERE device_id=? AND revoked_at IS NULL AND expires_at>=? ORDER BY created_at',(str(device_id),time.time())).fetchall()
        return [self._row(r) for r in rows]
    def purge_expired(self):
        with self._con() as con:cur=con.execute('DELETE FROM pwa_sessions WHERE expires_at<?',(time.time(),))
        return int(cur.rowcount)
