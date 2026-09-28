from __future__ import annotations
import json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from core.security import new_bearer_secret, verify_secret

def now(): return datetime.now(timezone.utc).isoformat()
class DeviceRegistry:
    DEFAULT_SCOPES={'ai:chat','memory:read','memory:write','knowledge:read','knowledge:write','activities:read','workflow:read','workflow:write','device:read'}
    OWNER_SCOPES=DEFAULT_SCOPES|{'device:admin','workflow:approve','knowledge:private','memory:sensitive','qualification:read','qualification:record'}
    def __init__(self,path:Path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._con() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,name TEXT NOT NULL,platform TEXT NOT NULL,salt TEXT NOT NULL,token_hash TEXT NOT NULL,created_at TEXT NOT NULL,last_seen_at TEXT,revoked INTEGER NOT NULL DEFAULT 0)''')
            c.execute('''CREATE TABLE IF NOT EXISTS device_metadata(device_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(device_id,key),FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE)''')
            c.execute('''CREATE TABLE IF NOT EXISTS device_permissions(device_id TEXT PRIMARY KEY,scopes_json TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE)''')
            c.execute('''INSERT INTO device_permissions(device_id,scopes_json,updated_at) SELECT d.id,?,? FROM devices d LEFT JOIN device_permissions p ON p.device_id=d.id WHERE d.platform='ios-pwa' AND p.device_id IS NULL''',(json.dumps(sorted(self.OWNER_SCOPES)),now()))
            c.execute('''INSERT INTO device_permissions(device_id,scopes_json,updated_at) SELECT d.id,?,? FROM devices d LEFT JOIN device_permissions p ON p.device_id=d.id WHERE d.platform!='ios-pwa' AND p.device_id IS NULL''',(json.dumps(sorted(self.DEFAULT_SCOPES)),now()))
    def _con(self):c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
    def enroll(self,name,platform):
        did=str(uuid.uuid4());token,salt,h=new_bearer_secret()
        with self._con() as c:c.execute('INSERT INTO devices VALUES(?,?,?,?,?,?,?,0)',(did,name,platform,salt,h,now(),None));c.execute('INSERT INTO device_permissions VALUES(?,?,?)',(did,json.dumps(sorted(self.DEFAULT_SCOPES)),now()))
        return {'id':did,'name':name,'platform':platform},token
    def authenticate(self,device_id,token):
        with self._con() as c:
            row=c.execute('SELECT * FROM devices WHERE id=?',(device_id,)).fetchone()
            if not row or row['revoked']:return False
            ok=verify_secret(token,row['salt'],row['token_hash'])
            if ok:c.execute('UPDATE devices SET last_seen_at=? WHERE id=?',(now(),device_id))
            return ok
    def is_active(self,device_id):
        with self._con() as c:return c.execute('SELECT 1 FROM devices WHERE id=? AND revoked=0',(device_id,)).fetchone() is not None
    def set_metadata(self,device_id,key,value):
        with self._con() as c:
            if not c.execute('SELECT 1 FROM devices WHERE id=? AND revoked=0',(device_id,)).fetchone():return False
            c.execute('INSERT INTO device_metadata(device_id,key,value,updated_at) VALUES(?,?,?,?) ON CONFLICT(device_id,key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at',(device_id,key,value,now()));return True
    def metadata(self,device_id):
        with self._con() as c:return {r['key']:r['value'] for r in c.execute('SELECT key,value FROM device_metadata WHERE device_id=?',(device_id,))}
    def revoke(self,device_id):
        with self._con() as c:cur=c.execute('UPDATE devices SET revoked=1 WHERE id=?',(device_id,))
        if cur.rowcount:
            try:
                from integrations.state import invalidate_device_transactions
                invalidate_device_transactions(self.path.parent/'connectors.sqlite3',str(device_id))
            except Exception:pass
        return cur.rowcount==1
    def permissions(self,device_id):
        with self._con() as c:row=c.execute('SELECT scopes_json,updated_at FROM device_permissions WHERE device_id=?',(device_id,)).fetchone()
        if not row:return {'scopes':[],'updated_at':None}
        try:scopes=sorted({str(x) for x in json.loads(row['scopes_json'])})
        except Exception:scopes=[]
        return {'scopes':scopes,'updated_at':row['updated_at']}
    def authorize(self,device_id,scope):return self.is_active(device_id) and scope in set(self.permissions(device_id)['scopes'])
    def set_permissions(self,device_id,scopes):
        allowed=set(self.OWNER_SCOPES);clean=sorted({str(x).strip() for x in scopes if str(x).strip()})
        if not set(clean).issubset(allowed):raise ValueError('Unsupported device permission scope')
        with self._con() as c:
            if not c.execute('SELECT 1 FROM devices WHERE id=? AND revoked=0',(device_id,)).fetchone():raise KeyError('Active device not found')
            c.execute('INSERT INTO device_permissions(device_id,scopes_json,updated_at) VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET scopes_json=excluded.scopes_json,updated_at=excluded.updated_at',(device_id,json.dumps(clean),now()))
        return self.permissions(device_id)
    def list(self):
        with self._con() as c:rows=[dict(r) for r in c.execute('SELECT id,name,platform,created_at,last_seen_at,revoked FROM devices ORDER BY created_at DESC')]
        for row in rows:row['permissions']=self.permissions(row['id'])['scopes'];row['metadata']=self.metadata(row['id'])
        return rows
