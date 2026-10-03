from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from memory.policy import require_storable


def now():
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    STORABLE_SQL = "lower(replace(replace(trim(COALESCE(sensitivity,'')),'-','_'),' ','_')) != 'never_store'"

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
            message_columns = {row['name'] for row in con.execute('PRAGMA table_info(messages)')}
            message_additions = {
                'conversation_id': 'TEXT',
                'device_id': 'TEXT',
                'metadata_json': "TEXT NOT NULL DEFAULT '{}'",
            }
            for name, definition in message_additions.items():
                if name not in message_columns:
                    con.execute(f'ALTER TABLE messages ADD COLUMN {name} {definition}')
            con.execute('CREATE INDEX IF NOT EXISTS idx_memories_subject_type ON memories(type,subject)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_memories_temporal ON memories(occurred_at,created_at)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_memory_usage_memory ON memory_usage(memory_id,used_at)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages(conversation_id,created_at)')

    def add_message(self, role, content, *, conversation_id=None, device_id=None, metadata=None):
        message_id = str(uuid.uuid4())
        with self.lock, self.con() as con:
            con.execute(
                '''INSERT INTO messages(id,role,content,created_at,conversation_id,device_id,metadata_json)
                   VALUES(?,?,?,?,?,?,?)''',
                (message_id, role, content, now(), conversation_id, device_id, json.dumps(metadata or {}, default=str)),
            )
        return message_id

    def recent_messages(self, limit=20, *, conversation_id=None):
        with self.con() as con:
            if conversation_id:
                rows = con.execute(
                    'SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?',
                    (conversation_id, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    'SELECT role,content FROM messages ORDER BY created_at DESC LIMIT ?',
                    (limit,),
                ).fetchall()
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
        require_storable(sensitivity=sensitivity, metadata=metadata)
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
            row = con.execute(
                f'SELECT * FROM memories WHERE id=? AND {self.STORABLE_SQL}',
                (memory_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_memory(self, memory_id: str, **changes):
        require_storable(
            sensitivity=changes.get('sensitivity'),
            metadata=changes.get('metadata'),
        )
        allowed = {
            'type', 'subject', 'content', 'source', 'confidence', 'verified', 'sensitivity',
            'parent_id', 'importance', 'occurred_at', 'valid_from', 'valid_to', 'superseded_by',
        }
        fields = {key: value for key, value in changes.items() if key in allowed}
        if 'parent_id' in fields and fields['parent_id'] is not None:
            fields['parent_id'] = str(fields['parent_id'])
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
            con.execute('BEGIN IMMEDIATE')
            if fields.get('parent_id') is not None:
                parent_id = fields['parent_id']
                if parent_id == str(memory_id):
                    raise ValueError('A memory cannot be its own parent')
                if not con.execute(f'SELECT 1 FROM memories WHERE id=? AND {self.STORABLE_SQL}', (parent_id,)).fetchone():
                    raise ValueError('Parent memory was not found')
                cursor, seen = parent_id, set()
                while cursor:
                    if cursor == str(memory_id):
                        raise ValueError('Moving this memory would create a hierarchy cycle')
                    if cursor in seen:
                        raise ValueError('The existing memory hierarchy contains a cycle')
                    seen.add(cursor)
                    row = con.execute('SELECT parent_id FROM memories WHERE id=?', (cursor,)).fetchone()
                    cursor = row['parent_id'] if row else None
            cur = con.execute(
                f'UPDATE memories SET {query} WHERE id=? AND {self.STORABLE_SQL}',
                [*fields.values(), memory_id],
            )
        return cur.rowcount == 1

    def relate(self, source_id, relation, target_id):
        if not self.get(source_id) or not self.get(target_id):
            raise KeyError('memory not found')
        relation_id = str(uuid.uuid4())
        with self.lock, self.con() as con:
            con.execute('INSERT INTO relations VALUES(?,?,?,?,?)', (relation_id, source_id, relation, target_id, now()))
        return relation_id

    def search(self, q, limit=20, *, active_only=False):
        term = f'%{q}%'
        active_clause = ' AND valid_to IS NULL' if active_only else ''
        with self.con() as con:
            rows = con.execute(
                f'''SELECT * FROM memories WHERE {self.STORABLE_SQL} AND (subject LIKE ? OR content LIKE ?){active_clause}
                    ORDER BY updated_at DESC LIMIT ?''',
                (term, term, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def active_subject(self, type: str, subject: str, limit=20):
        with self.con() as con:
            rows = con.execute(
                f'''SELECT * FROM memories WHERE {self.STORABLE_SQL} AND lower(type)=lower(?) AND lower(subject)=lower(?) AND valid_to IS NULL
                   ORDER BY updated_at DESC LIMIT ?''',
                (type, subject, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def supersede(self, older_id: str, newer_id: str, *, reason='newer supported memory'):
        if not self.get(older_id) or not self.get(newer_id):
            raise KeyError('memory not found')
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
        if not self.get(older_id) or not self.get(newer_id):
            raise KeyError('memory not found')
        conflict_id = str(uuid.uuid4())
        with self.lock, self.con() as con:
            con.execute(
                'INSERT INTO memory_conflicts VALUES(?,?,?,?,?,?)',
                (conflict_id, older_id, newer_id, resolution, reason, now()),
            )
        return conflict_id

    def conflicts(self, limit=100):
        with self.con() as con:
            rows = [
                dict(row)
                for row in con.execute(
                    'SELECT * FROM memory_conflicts ORDER BY created_at DESC LIMIT ?',
                    (limit,),
                )
            ]
        return [row for row in rows if self.get(row['older_id']) and self.get(row['newer_id'])]

    def record_usage(self, memory_id: str, *, query: str = '', score: float | None = None):
        usage_id = str(uuid.uuid4())
        stamp = now()
        with self.lock, self.con() as con:
            if not con.execute(
                f'SELECT 1 FROM memories WHERE id=? AND {self.STORABLE_SQL}',
                (memory_id,),
            ).fetchone():
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
        if not self.get(memory_id):
            return []
        with self.con() as con:
            return [dict(row) for row in con.execute('SELECT * FROM memory_usage WHERE memory_id=? ORDER BY used_at DESC LIMIT ?', (memory_id, limit))]

    def temporal_search(self, q='', *, start=None, end=None, memory_type=None, limit=100):
        clauses = [self.STORABLE_SQL]
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
            nodes = [
                dict(row)
                for row in con.execute(f'SELECT * FROM memories WHERE {self.STORABLE_SQL}').fetchall()
            ]
            allowed = {row['id'] for row in nodes}
            edges = [
                dict(row)
                for row in con.execute('SELECT * FROM relations').fetchall()
                if row['source_id'] in allowed and row['target_id'] in allowed
            ]
            return {'nodes': nodes, 'edges': edges}

    def graph_projection(self, *, limit=36, focal_id=None, memory_type=None, include_sensitive=True):
        """Return a bounded graph projection for owner-facing exploration."""
        bounded = max(1, min(int(limit), 60))
        with self.con() as con:
            clauses = [self.STORABLE_SQL]
            visibility = '' if include_sensitive else " AND lower(replace(replace(trim(COALESCE(sensitivity,'')),'-','_'),' ','_')) NOT IN ('sensitive','secret')"
            clauses.append('1=1' + visibility)
            params = []
            if memory_type and memory_type != 'all':
                clauses.append('lower(type)=lower(?)')
                params.append(str(memory_type))
            rows = [dict(row) for row in con.execute(
                f'SELECT * FROM memories WHERE {" AND ".join(clauses)} ORDER BY COALESCE(occurred_at,created_at) DESC,id LIMIT ?',
                [*params, bounded],
            ).fetchall()]
            by_id = {row['id']: row for row in rows}
            if focal_id:
                focus_visibility = '' if include_sensitive else " AND lower(replace(replace(trim(COALESCE(sensitivity,'')),'-','_'),' ','_')) NOT IN ('sensitive','secret')"
                focal = con.execute(f"SELECT * FROM memories WHERE id=? AND {self.STORABLE_SQL}{focus_visibility}", (str(focal_id),)).fetchone()
                if focal:
                    # Keep the requested focal node inside the caller's hard limit.
                    # The recent-node query may already have filled the projection.
                    if focal['id'] not in by_id and len(by_id) >= bounded:
                        by_id.pop(next(reversed(by_id)))
                    by_id[focal['id']] = dict(focal)
                    neighbors = con.execute(
                        f'''SELECT m.* FROM relations r JOIN memories m
                             ON m.id=CASE WHEN r.source_id=? THEN r.target_id ELSE r.source_id END
                             WHERE (r.source_id=? OR r.target_id=?) AND {self.STORABLE_SQL.replace('sensitivity', 'm.sensitivity')}
                               AND (? OR lower(replace(replace(trim(COALESCE(m.sensitivity,'')),'-','_'),' ','_')) NOT IN ('sensitive','secret'))
                             ORDER BY r.created_at DESC,m.id LIMIT ?''',
                        (str(focal_id), str(focal_id), str(focal_id), int(include_sensitive), min(24, bounded - 1)),
                    ).fetchall()
                    for row in neighbors:
                        if len(by_id) >= bounded:
                            break
                        by_id[row['id']] = dict(row)
            ids = list(by_id)
            if ids:
                marks = ','.join('?' for _ in ids)
                edges = [dict(row) for row in con.execute(
                    f'SELECT * FROM relations WHERE source_id IN ({marks}) AND target_id IN ({marks}) ORDER BY created_at DESC LIMIT 120',
                    [*ids, *ids],
                ).fetchall()]
            else:
                edges = []
            type_rows = con.execute(
                f'''SELECT lower(type) AS type,COUNT(*) AS total FROM memories WHERE {self.STORABLE_SQL}{visibility}
                    GROUP BY lower(type) ORDER BY lower(type)'''
            ).fetchall()
            total = int(con.execute(f'SELECT COUNT(*) FROM memories WHERE {self.STORABLE_SQL}{visibility}').fetchone()[0])
        return {'nodes': list(by_id.values()), 'edges': edges, 'type_counts': [dict(row) for row in type_rows], 'total': total, 'limited': True, 'limit': bounded}

    def tree_children(self, *, parent_id=None, limit=100, offset=0, include_sensitive=True, entity_type=None):
        """Fetch a single hierarchy branch, with counts scoped to visible rows."""
        bounded = max(1, min(int(limit), 200))
        start = max(0, min(int(offset), 1000000))
        visibility = '' if include_sensitive else " AND lower(replace(replace(trim(COALESCE(m.sensitivity,'')),'-','_'),' ','_')) NOT IN ('sensitive','secret')"
        child_visibility = '' if include_sensitive else " AND lower(replace(replace(trim(COALESCE(c.sensitivity,'')),'-','_'),' ','_')) NOT IN ('sensitive','secret')"
        m_storable = "lower(replace(replace(trim(COALESCE(m.sensitivity,'')),'-','_'),' ','_')) != 'never_store'"
        child_storable = "lower(replace(replace(trim(COALESCE(c.sensitivity,'')),'-','_'),' ','_')) != 'never_store'"
        type_clause = '' if not entity_type or entity_type == 'all' else ' AND lower(m.type)=lower(?)'
        query_params = (parent_id, str(entity_type)) if type_clause else (parent_id,)
        with self.con() as con:
            rows = [dict(row) for row in con.execute(
                f'''SELECT m.*,
                    (SELECT COUNT(*) FROM memories c WHERE c.parent_id=m.id AND {child_storable}{child_visibility}) AS child_count
                    FROM memories m WHERE {m_storable}{visibility} AND m.parent_id IS ?{type_clause}
                    ORDER BY lower(COALESCE(m.type,'')),lower(COALESCE(m.subject,'')),m.id LIMIT ? OFFSET ?''',
                (*query_params, bounded, start),
            ).fetchall()]
            total = int(con.execute(
                f'''SELECT COUNT(*) FROM memories m WHERE {m_storable}{visibility} AND m.parent_id IS ?{type_clause}''',
                query_params,
            ).fetchone()[0])
            type_rows = con.execute(
                f'''SELECT lower(m.type) AS type,COUNT(*) AS total FROM memories m WHERE {m_storable}{visibility}
                    GROUP BY lower(m.type) ORDER BY lower(m.type)'''
            ).fetchall()
        return {'nodes': rows, 'total': total, 'limit': bounded, 'offset': start, 'types': [dict(row) for row in type_rows]}

    def tree(self):
        """Return parent/child memory structure without changing graph semantics."""
        nodes = self.graph()['nodes']
        by_id = {row['id']: {**row, 'children': []} for row in nodes}
        roots = []
        for item in by_id.values():
            parent = by_id.get(item.get('parent_id'))
            if parent:
                parent['children'].append(item)
            else:
                roots.append(item)
        key = lambda item: (str(item.get('type') or ''), str(item.get('subject') or '').lower())
        def sort_branch(branch):
            branch.sort(key=key)
            for child in branch:
                sort_branch(child['children'])
        sort_branch(roots)
        return roots

    def delete_memory(self, memory_id: str):
        """Permanently remove one owner-selected memory and its dependent evidence."""
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM memories WHERE id=?', (memory_id,)).fetchone():
                return False
            con.execute('DELETE FROM relations WHERE source_id=? OR target_id=?', (memory_id, memory_id))
            con.execute('DELETE FROM memory_usage WHERE memory_id=?', (memory_id,))
            con.execute('DELETE FROM memory_conflicts WHERE older_id=? OR newer_id=?', (memory_id, memory_id))
            con.execute('UPDATE memories SET parent_id=NULL WHERE parent_id=?', (memory_id,))
            con.execute('UPDATE memories SET superseded_by=NULL WHERE superseded_by=?', (memory_id,))
            con.execute('DELETE FROM memories WHERE id=?', (memory_id,))
        return True

    def apply_retention(self, *, older_than_days: int, sensitivity: str | None = None, dry_run: bool = True):
        days = max(1, min(int(older_than_days), 36500))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        clauses = [self.STORABLE_SQL, 'COALESCE(occurred_at,created_at)<?']
        params = [cutoff]
        if sensitivity:
            clauses.append('sensitivity=?')
            params.append(str(sensitivity))
        where = ' AND '.join(clauses)
        with self.lock, self.con() as con:
            ids = [row['id'] for row in con.execute(f'SELECT id FROM memories WHERE {where}', params)]
        if not dry_run:
            for memory_id in ids:
                self.delete_memory(memory_id)
        return {'dry_run': bool(dry_run), 'older_than_days': days, 'matched': len(ids), 'memory_ids': ids}

    def ambient_cleanup_candidates(self, *, older_than_days: int, limit: int = 200):
        """Return only stale, unused, low-importance conversation-derived memories."""
        days = max(30, min(int(older_than_days), 3650))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.con() as con:
            rows = con.execute(
                f'''SELECT m.id FROM memories m
                    WHERE {self.STORABLE_SQL.replace('sensitivity', 'm.sensitivity')}
                      AND lower(COALESCE(m.source,'')) LIKE '%user-message%'
                      AND lower(COALESCE(m.sensitivity,'normal'))='normal'
                      AND COALESCE(m.importance,0.5)<0.4
                      AND COALESCE(m.use_count,0)=0
                      AND m.updated_at<?
                      AND m.parent_id IS NULL
                      AND NOT EXISTS(SELECT 1 FROM memories c WHERE c.parent_id=m.id)
                      AND NOT EXISTS(SELECT 1 FROM relations r WHERE r.source_id=m.id OR r.target_id=m.id)
                    ORDER BY m.updated_at LIMIT ?''', (cutoff, max(1, min(int(limit), 1000))),
            ).fetchall()
        return [row['id'] for row in rows]

    def export(self, *, include_sensitive: bool = True):
        with self.con() as con:
            clauses = [self.STORABLE_SQL]
            if not include_sensitive:
                clauses.append("sensitivity NOT IN ('sensitive','secret')")
            where = ' WHERE ' + ' AND '.join(clauses)
            memories = [dict(row) for row in con.execute(f'SELECT * FROM memories{where} ORDER BY created_at')]
            allowed = {row['id'] for row in memories}
            relations = [
                dict(row) for row in con.execute('SELECT * FROM relations ORDER BY created_at')
                if row['source_id'] in allowed and row['target_id'] in allowed
            ]
        return {'version': 1, 'exported_at': now(), 'memories': memories, 'relations': relations}

    def audit_entries(self, category: str | None = None, limit: int = 200):
        with self.con() as con:
            if category:
                rows = con.execute(
                    'SELECT * FROM audit WHERE category=? ORDER BY created_at DESC LIMIT ?',
                    (category, max(1, min(int(limit), 1000))),
                ).fetchall()
            else:
                rows = con.execute(
                    'SELECT * FROM audit ORDER BY created_at DESC LIMIT ?',
                    (max(1, min(int(limit), 1000)),),
                ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item['payload'] = json.loads(item.pop('payload_json') or '{}')
            output.append(item)
        return output

    def audit(self, category, action, payload=None):
        audit_id = str(uuid.uuid4())
        with self.lock, self.con() as con:
            con.execute(
                'INSERT INTO audit VALUES(?,?,?,?,?)',
                (audit_id, category, action, json.dumps(payload or {}, default=str), now()),
            )
        return audit_id
