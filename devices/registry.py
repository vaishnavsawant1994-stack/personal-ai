from __future__ import annotations
import sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from core.security import new_bearer_secret, verify_secret

def now(): return datetime.now(timezone.utc).isoformat()

class DeviceRegistry:
    def __init__(self,path:Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._con() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS devices(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,platform TEXT NOT NULL,
                salt TEXT NOT NULL,token_hash TEXT NOT NULL,created_at TEXT NOT NULL,
                last_seen_at TEXT,revoked INTEGER NOT NULL DEFAULT 0)''')
            c.execute('''CREATE TABLE IF NOT EXISTS device_metadata(
                device_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,updated_at TEXT NOT NULL,
                PRIMARY KEY(device_id,key),FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE)''')

    def _con(self):
        c=sqlite3.connect(self.path); c.row_factory=sqlite3.Row; return c

    def enroll(self,name:str,platform:str):
        device_id=str(uuid.uuid4()); token,salt,token_hash=new_bearer_secret()
        with self._con() as c:
            c.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?,0)",(device_id,name,platform,salt,token_hash,now(),None))
        return {"id":device_id,"name":name,"platform":platform},token

    def authenticate(self,device_id:str,token:str)->bool:
        with self._con() as c:
            row=c.execute("SELECT * FROM devices WHERE id=?",(device_id,)).fetchone()
            if not row or row["revoked"]: return False
            ok=verify_secret(token,row["salt"],row["token_hash"])
            if ok: c.execute("UPDATE devices SET last_seen_at=? WHERE id=?",(now(),device_id))
            return ok

    def is_active(self,device_id:str)->bool:
        with self._con() as c:return c.execute("SELECT 1 FROM devices WHERE id=? AND revoked=0",(device_id,)).fetchone() is not None

    def set_metadata(self,device_id:str,key:str,value:str):
        with self._con() as c:
            if not c.execute("SELECT 1 FROM devices WHERE id=? AND revoked=0",(device_id,)).fetchone():return False
            c.execute("INSERT INTO device_metadata(device_id,key,value,updated_at) VALUES(?,?,?,?) ON CONFLICT(device_id,key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(device_id,key,value,now()))
            return True

    def metadata(self,device_id:str):
        with self._con() as c:return {r['key']:r['value'] for r in c.execute("SELECT key,value FROM device_metadata WHERE device_id=?",(device_id,))}

    def revoke(self,device_id:str)->bool:
        with self._con() as c:
            cur=c.execute("UPDATE devices SET revoked=1 WHERE id=?",(device_id,)); return cur.rowcount==1

    def list(self):
        with self._con() as c:
            return [dict(r) for r in c.execute("SELECT id,name,platform,created_at,last_seen_at,revoked FROM devices ORDER BY created_at DESC")]
