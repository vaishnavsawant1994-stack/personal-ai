from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json, sqlite3, uuid


def _now(): return datetime.now(timezone.utc).isoformat()


class LifeGraph:
    """P5 evidence-bearing life/knowledge graph with causal relationships."""
    TYPES={'person','project','decision','event','goal','habit','place','document','photo','conversation','knowledge_source','memory'}
    RELATIONS={'related_to','part_of','caused_by','led_to','supports','contradicts','decided_because','involves','occurred_at','supersedes','evidence_for'}

    def __init__(self,path:Path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as c:c.executescript('''
        CREATE TABLE IF NOT EXISTS life_nodes(id TEXT PRIMARY KEY,type TEXT NOT NULL,label TEXT NOT NULL,summary TEXT NOT NULL,occurred_at TEXT,source TEXT NOT NULL,confidence REAL NOT NULL,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS life_edges(id TEXT PRIMARY KEY,src TEXT NOT NULL,dst TEXT NOT NULL,relation TEXT NOT NULL,rationale TEXT NOT NULL,source TEXT NOT NULL,confidence REAL NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(src) REFERENCES life_nodes(id),FOREIGN KEY(dst) REFERENCES life_nodes(id));
        CREATE INDEX IF NOT EXISTS idx_life_nodes_type ON life_nodes(type); CREATE INDEX IF NOT EXISTS idx_life_edges_src ON life_edges(src); CREATE INDEX IF NOT EXISTS idx_life_edges_dst ON life_edges(dst);
        ''')
    def node(self,type,label,*,summary='',occurred_at=None,source='user',confidence=1.0,metadata=None):
        type=type.strip().lower()
        if type not in self.TYPES: raise ValueError('invalid life node type')
        nid=str(uuid.uuid4());stamp=_now()
        with sqlite3.connect(self.path) as c:c.execute('INSERT INTO life_nodes VALUES(?,?,?,?,?,?,?,?,?,?)',(nid,type,label.strip(),summary.strip(),occurred_at,source,max(0,min(float(confidence),1)),json.dumps(metadata or {},default=str),stamp,stamp))
        return nid
    def relate(self,src,dst,relation,*,rationale='',source='user',confidence=1.0):
        relation=relation.strip().lower()
        if relation not in self.RELATIONS: raise ValueError('invalid relation')
        eid=str(uuid.uuid4())
        with sqlite3.connect(self.path) as c:
            exists=c.execute('SELECT COUNT(*) FROM life_nodes WHERE id IN (?,?)',(src,dst)).fetchone()[0]
            if exists != 2: raise KeyError('both graph nodes must exist')
            c.execute('INSERT INTO life_edges VALUES(?,?,?,?,?,?,?,?)',(eid,src,dst,relation,rationale,source,max(0,min(float(confidence),1)),_now()))
        return eid
    def graph(self,*,type=None,limit=500):
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row
            if type: nodes=c.execute('SELECT * FROM life_nodes WHERE type=? ORDER BY COALESCE(occurred_at,created_at) DESC LIMIT ?',(type,int(limit))).fetchall()
            else:nodes=c.execute('SELECT * FROM life_nodes ORDER BY COALESCE(occurred_at,created_at) DESC LIMIT ?',(int(limit),)).fetchall()
            ids=[r['id'] for r in nodes]; edges=[]
            if ids:
                marks=','.join('?'*len(ids));edges=c.execute(f'SELECT * FROM life_edges WHERE src IN ({marks}) OR dst IN ({marks}) ORDER BY created_at DESC',(*ids,*ids)).fetchall()
        return {'nodes':[dict(r) for r in nodes],'edges':[dict(r) for r in edges]}
    def timeline(self,limit=100):
        return self.graph(limit=limit)['nodes']
    def explain_decision(self,decision_id:str):
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row
            decision=c.execute("SELECT * FROM life_nodes WHERE id=? AND type='decision'",(decision_id,)).fetchone()
            if not decision: raise KeyError('decision not found')
            edges=c.execute("SELECT e.*,n.type AS evidence_type,n.label AS evidence_label,n.summary AS evidence_summary FROM life_edges e JOIN life_nodes n ON n.id=e.dst WHERE e.src=? AND e.relation IN ('decided_because','caused_by','supports','evidence_for') ORDER BY e.confidence DESC",(decision_id,)).fetchall()
        evidence=[dict(r) for r in edges]
        return {'decision':dict(decision),'why':evidence,'answerable':bool(evidence),'warning':None if evidence else 'No evidence-backed reason has been recorded; do not invent one.'}
