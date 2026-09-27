from __future__ import annotations
import json, math, sqlite3, uuid
from pathlib import Path
def cosine(a,b):
    dot=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(x*x for x in b)); return dot/(na*nb) if na and nb else 0.0
class VectorStore:
    def __init__(self,path:Path,embedder):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.embedder=embedder
        with self._con() as c:c.execute('CREATE TABLE IF NOT EXISTS vectors(id TEXT PRIMARY KEY,memory_id TEXT UNIQUE,text TEXT,vector_json TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    def _con(self): c=sqlite3.connect(self.path); c.row_factory=sqlite3.Row; return c
    def upsert(self,memory_id:str,text:str):
        v=list(map(float,self.embedder(text))); i=str(uuid.uuid4())
        with self._con() as c:c.execute('INSERT INTO vectors(id,memory_id,text,vector_json) VALUES(?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET text=excluded.text,vector_json=excluded.vector_json,updated_at=CURRENT_TIMESTAMP',(i,memory_id,text,json.dumps(v)))
    def search(self,query:str,limit:int=8,min_score:float=-1.0):
        q=list(map(float,self.embedder(query))); out=[]
        with self._con() as c: rows=c.execute('SELECT * FROM vectors').fetchall()
        for r in rows:
            s=cosine(q,json.loads(r['vector_json']))
            if s>=min_score: out.append({'memory_id':r['memory_id'],'text':r['text'],'score':s})
        return sorted(out,key=lambda x:x['score'],reverse=True)[:limit]
