from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


def now():
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self._init()

    def con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        with self.con() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages(
                  id TEXT PRIMARY KEY, role TEXT, content TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS memories(
                  id TEXT PRIMARY KEY, type TEXT, subject TEXT, content TEXT, source TEXT,
                  confidence REAL, verified INTEGER, sensitivity TEXT, parent_id TEXT,
                  tags_json TEXT, created_at TEXT, updated_at TEXT);
                CREATE TABLE IF NOT EXISTS relations(
                  id TEXT PRIMARY KEY, source_id TEXT, relation TEXT, target_id TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS tasks(
                  id TEXT PRIMARY KEY, title TEXT, status TEXT, due_at TEXT, payload_json TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS audit(
                  id TEXT PRIMARY KEY, category TEXT, action TEXT, payload_json TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS memory_usage(
                  id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, query TEXT, score REAL,
                  used_at TEXT NOT NULL, FOREIGN KEY(memory_id) REFERENCES memories(id));
                CREATE TABLE IF NOT EXISTS memory_conflicts(
                  id TEXT PRIMARY KEY, older_id TEXT NOT NULL, newer_id TEXT NOT NULL,
                  resolution TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL);
                """
            )
            columns = {row['name'] for row in con.execute('PRAGMA table_info(memories)')}
            additions = {
                'importance': 'REAL NOT NULL DEFAULT 0.5',
                'occurred_at': 'TEXT',
                'last_used_at': 'TEXT',
                'use_count': 'INTEGER NOT NULL DEFAULT 0',
                'valid_from': 'TEXT',
                'valid_to': 'TEXT',
                'superseded_by': 'TEXT',
                'evidence_json': "TEXT NOT NULL DEFAULT '[]'",
                'metadata_json': "TEXT NOT NULL DEFAULT '{}'",
            }
            for name, definition in additions.items():
                if name not in columns:
                    con.execute(f'ALTER TABLE memories ADD COLUMN {name} {definition}')
            con.execute('CREATE INDEX IF NOT EXISTS idx_memories_subject_type ON memories(type,subject)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_memories_temporal ON memories(occurred_at,created_at)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_memory_usage_memory ON memory_usage(memory_id,used_at)')

    def add_message(self, role, content):
        message_id = str(uuid.uuid4())
        with self.lock, self.con() as con:
            con.execute('INSERT INTO messages VALUES(?,?,?,?)', (message_id, role, content, now()))
        return message_id

    def recent_messages(self, limit=20):
        with self.con() as con:
            rows = con.execute('SELECT role,content FROM messages ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def remember(
        self,
        *,
        type,
        subject,
        content,
        source='user',
        confidence=1.0,
        verified=False,
        sensitivity='normal',
        parent_id=None,
        tags=None,
        importance=0.5,
        occurred_at=None,
        valid_from=None,
        evidence=None,
        metadata=None,
    ):
        memory_id = str(uuid.uuid4())
        stamp = now()
        with self.lock, self.con() as con:
            con.execute(
                '''INSERT INTO memories(
                    id,type,subject,content,source,confidence,verified,sensitivity,parent_id,tags_json,
                    created_at,updated_at,importance,occurred_at,last_used_at,use_count,valid_from,valid_to,
                    superseded_by,evidence_json,metadata_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)''',
                (
                    memory_id,
                    type,
                    subject,
                    content,
                    source,
                    float(confidence),
                    int(verified),
                    sensitivity,
                    parent_id,
                    json.dumps(tags or []),
                    stamp,
                    stamp,
                    max(0.0, min(1.0, float(importance))),
                    occurred_at,
                    None,
                    0,
                    valid_from or occurred_at or stamp,
                    json.dumps(evidence or [], default=str),
                    json.dumps(metadata or {}, default=str),
                ),
            )
        return memory_id

    def get(self, memory_id: str):
        with self.con() as con:
            row = con.execute('SELECT * FROM memories WHERE id=?', (memory_id,)).fetchone()
        return dict(row) if row else None

    def update_memory(self, memory_id: str, **changes):
        allowed = {
            'type', 'subject', 'content', 'source', 'confidence', 'verified', 'sensitivity',
            'parent_id', 'importance', 'occurred_at', 'valid_from', 'valid_to', 'superseded_by',
        }
        fields = {key: value for key, value in changes.items() if key in allowed}
        if 'tags' in changes:
            fields['tags_json'] = json.dumps(changes['tags'] or [])
        if 'evidence' in changes:
            fields['evidence_json'] = json.dumps(changes['evidence'] or [], default=str)
        if 'metadata' in changes:
            fields['metadata_json'] = json.dumps(changes['metadata'] or {}, default=str)
        if not fields:
            return False
        fields['updated_at'] = now()
        query = ','.join(f'{key}=?' for key in fields)
        with self.lock, self.con() as con:
            cur = con.execute(f'UPDATE memories SET {query} WHERE id=?', [*fields.values(), memory_id])
        return cur.rowcount == 1

    def relate(self, source_id, relation, target_id):
        relation_id = str(uuid.uuid4())
        with self.lock, self.con() as con:
            con.execute('INSERT INTO relations VALUES(?,?,?,?,?)', (relation_id, source_id, relation, target_id, now()))
        return relation_id

    def search(self, q, limit=20, *, active_only=False):
        term = f'%{q}%'
        active_clause = ' AND valid_to IS NULL' if active_only else ''
        with self.con() as con:
            rows = con.execute(
                f'''SELECT * FROM memories WHERE (subject LIKE ? OR content LIKE ?){active_clause}
                    ORDER BY updated_at DESC LIMIT ?''',
                (term, term, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def active_subject(self, type: str, subject: str, limit=20):
        with self.con() as con:
            rows = con.execute(
                '''SELECT * FROM memories WHERE lower(type)=lower(?) AND lower(subject)=lower(?) AND valid_to IS NULL
                   ORDER BY updated_at DESC LIMIT ?''',
                (type, subject, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def supersede(self, older_id: str, newer_id: str, *, reason='newer supported memory'):
        stamp = now()
        with self.lock, self.con() as con:
            older = con.execute('SELECT id FROM memories WHERE id=?', (older_id,)).fetchone()
            newer = con.execute('SELECT id FROM memories WHERE id=?', (newer_id,)).fetchone()
            if not older or not newer:
                raise KeyError('memory not found')
            con.execute(
                'UPDATE memories SET valid_to=?,superseded_by=?,updated_at=? WHERE id=? AND valid_to IS NULL',
                (stamp, newer_id, stamp, older_id),
            )
            conflict_id = str(uuid.uuid4())
            con.execute(
                'INSERT INTO memory_conflicts VALUES(?,?,?,?,?,?)',
                (conflict_id, older_id, newer_id, 'superseded', reason, stamp),
            )
        return conflict_id

    def conflict(self, older_id: str, newer_id: str, *, resolution='unresolved', reason='conflicting supported memories'):
        conflict_id = str(uuid.uuid4())
        with self.lock, self.con() as con:
            con.execute(
                'INSERT INTO memory_conflicts VALUES(?,?,?,?,?,?)',
                (conflict_id, older_id, newer_id, resolution, reason, now()),
            )
        return conflict_id

    def conflicts(self, limit=100):
        with self.con() as con:
            return [dict(row) for row in con.execute('SELECT * FROM memory_conflicts ORDER BY created_at DESC LIMIT ?', (limit,))]

    def record_usage(self, memory_id: str, *, query: str = '', score: float | None = None):
        usage_id = str(uuid.uuid4())
        stamp = now()
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM memories WHERE id=?', (memory_id,)).fetchone():
                return None
            con.execute(
                'INSERT INTO memory_usage VALUES(?,?,?,?,?)',
                (usage_id, memory_id, query, score, stamp),
            )
            con.execute(
                'UPDATE memories SET last_used_at=?,use_count=use_count+1,updated_at=updated_at WHERE id=?',
                (stamp, memory_id),
            )
        return usage_id

    def usage(self, memory_id: str, limit=100):
        with self.con() as con:
            return [dict(row) for row in con.execute('SELECT * FROM memory_usage WHERE memory_id=? ORDER BY used_at DESC LIMIT ?', (memory_id, limit))]

    def temporal_search(self, q='', *, start=None, end=None, memory_type=None, limit=100):
        clauses = []
        params = []
        if q:
            clauses.append('(subject LIKE ? OR content LIKE ?)')
            params.extend([f'%{q}%', f'%{q}%'])
        if start:
            clauses.append('COALESCE(occurred_at,created_at)>=?')
            params.append(start)
        if end:
            clauses.append('COALESCE(occurred_at,created_at)<=?')
            params.append(end)
        if memory_type:
            clauses.append('lower(type)=lower(?)')
            params.append(memory_type)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        params.append(max(1, min(int(limit), 1000)))
        with self.con() as con:
            rows = con.execute(
                f'SELECT * FROM memories{where} ORDER BY COALESCE(occurred_at,created_at) DESC LIMIT ?',
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def graph(self):
        with self.con() as con:
            return {
                'nodes': [dict(row) for row in con.execute('SELECT * FROM memories').fetchall()],
                'edges': [dict(row) for row in con.execute('SELECT * FROM relations').fetchall()],
            }

    def audit(self, category, action, payload=None):
        audit_id = str(uuid.uuid4())
        with self.lock, self.con() as con:
            con.execute(
                'INSERT INTO audit VALUES(?,?,?,?,?)',
                (audit_id, category, action, json.dumps(payload or {}, default=str), now()),
            )
        return audit_id
