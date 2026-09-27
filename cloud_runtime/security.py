from __future__ import annotations
import hashlib,hmac,secrets,sqlite3,time,uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

DEFAULT_SCOPES=("ai:chat","status:read","memory:read","approval:read","approval:write")

def _hash(secret:str)->str:return hashlib.sha256(secret.encode()).hexdigest()
def _now()->int:return int(time.time())

@dataclass(frozen=True)
class Session:
    id:str;device_id:str;scopes:tuple[str,...];expires_at:int

class CloudSessionStore:
    """Opaque, hashed, revocable short-lived sessions. Raw tokens are never persisted."""
    def __init__(self,path:Path,ttl_seconds:int=900):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.ttl_seconds=max(60,int(ttl_seconds));self.lock=RLock()
        with self._con() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS cloud_sessions(
              id TEXT PRIMARY KEY,device_id TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,
              scopes TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
              revoked INTEGER NOT NULL DEFAULT 0,last_seen_at INTEGER);
            CREATE TABLE IF NOT EXISTS cloud_nonces(
              session_id TEXT NOT NULL,nonce_hash TEXT NOT NULL,seen_at INTEGER NOT NULL,
              PRIMARY KEY(session_id,nonce_hash));
            CREATE TABLE IF NOT EXISTS cloud_state(
              key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at INTEGER NOT NULL);
            ''')
    def _con(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
    def issue(self,device_id:str,scopes=DEFAULT_SCOPES):
        token=secrets.token_urlsafe(48);sid=str(uuid.uuid4());now=_now();exp=now+self.ttl_seconds;scope_string=' '.join(sorted(set(scopes)))
        with self.lock,self._con() as c:c.execute('INSERT INTO cloud_sessions VALUES(?,?,?,?,?,?,0,NULL)',(sid,device_id,_hash(token),scope_string,now,exp))
        return token,Session(sid,device_id,tuple(scope_string.split()),exp)
    def authenticate(self,token:str,required_scope:str|None=None)->Session|None:
        if not token:return None
        now=_now();digest=_hash(token)
        with self.lock,self._con() as c:
            row=c.execute('SELECT * FROM cloud_sessions WHERE token_hash=?',(digest,)).fetchone()
            if not row or row['revoked'] or row['expires_at']<=now:return None
            scopes=tuple(row['scopes'].split())
            if required_scope and required_scope not in scopes:return None
            c.execute('UPDATE cloud_sessions SET last_seen_at=? WHERE id=?',(now,row['id']))
            return Session(row['id'],row['device_id'],scopes,row['expires_at'])
    def revoke(self,session_id:str)->bool:
        with self.lock,self._con() as c:return c.execute('UPDATE cloud_sessions SET revoked=1 WHERE id=?',(session_id,)).rowcount==1
    def revoke_device(self,device_id:str)->int:
        with self.lock,self._con() as c:return c.execute('UPDATE cloud_sessions SET revoked=1 WHERE device_id=? AND revoked=0',(device_id,)).rowcount
    def accept_nonce(self,session_id:str,nonce:str,max_age_seconds:int=600)->bool:
        if not nonce or len(nonce)<16 or len(nonce)>256:return False
        now=_now();digest=_hash(nonce)
        with self.lock,self._con() as c:
            c.execute('DELETE FROM cloud_nonces WHERE seen_at<?',(now-max_age_seconds,))
            try:c.execute('INSERT INTO cloud_nonces VALUES(?,?,?)',(session_id,digest,now));return True
            except sqlite3.IntegrityError:return False
    def set_emergency_stop(self,enabled:bool):
        with self.lock,self._con() as c:c.execute("INSERT INTO cloud_state(key,value,updated_at) VALUES('emergency_stop',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",('1' if enabled else '0',_now()))
    def emergency_stopped(self)->bool:
        with self._con() as c:
            row=c.execute("SELECT value FROM cloud_state WHERE key='emergency_stop'").fetchone();return bool(row and row['value']=='1')

class OwnerAuthenticator:
    """Constant-time validation for a deployment-supplied owner bootstrap secret."""
    def __init__(self,secret:str):self._secret=(secret or '').strip()
    @property
    def configured(self)->bool:return len(self._secret)>=32
    def verify(self,candidate:str)->bool:return self.configured and hmac.compare_digest(self._secret,(candidate or '').strip())
