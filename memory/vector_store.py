from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from pathlib import Path


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


class VectorStore:
    """Derived Memory retrieval index; never canonical Memory truth."""

    def __init__(self, path: Path, embedder, *, owner_id: str = 'owner'):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.owner_id = str(owner_id or 'owner')
        with self._con() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS vectors(
                    id TEXT PRIMARY KEY,memory_id TEXT UNIQUE,text TEXT,vector_json TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
            self._ensure_column(con, 'vectors', 'owner_id', "TEXT NOT NULL DEFAULT 'owner'")
            self._ensure_column(con, 'vectors', 'embedding_model', "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(con, 'vectors', 'embedding_version', "TEXT NOT NULL DEFAULT '1'")
            self._ensure_column(con, 'vectors', 'dimensions', 'INTEGER')
            self._ensure_column(con, 'vectors', 'text_checksum', 'TEXT')
            con.execute('CREATE INDEX IF NOT EXISTS idx_vectors_owner ON vectors(owner_id,memory_id)')

    @staticmethod
    def _ensure_column(con, table, name, definition):
        columns = {row['name'] for row in con.execute(f'PRAGMA table_info({table})')}
        if name not in columns:
            con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')

    def _con(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA busy_timeout=30000')
        return con

    def _embedding_identity(self):
        source = getattr(self.embedder, '__self__', None)
        model = (getattr(self.embedder, 'model_name', None) or getattr(source, 'embedding_model', None)
                 or getattr(source, 'model_name', None) or getattr(source, 'name', None)
                 or getattr(self.embedder, '__qualname__', None) or 'replaceable-embedder')
        version = (getattr(self.embedder, 'version', None) or getattr(source, 'embedding_version', None)
                   or getattr(source, 'version', None) or '1')
        return str(model)[:200], str(version)[:100]

    def upsert(self, memory_id: str, text: str, *, owner_id: str | None = None):
        owner = str(owner_id or self.owner_id)
        clean = str(text)
        vector = list(map(float, self.embedder(clean)))
        model, version = self._embedding_identity()
        checksum = hashlib.sha256(clean.encode()).hexdigest()
        row_id = str(uuid.uuid4())
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('''INSERT INTO vectors(id,memory_id,text,vector_json,owner_id,embedding_model,embedding_version,dimensions,text_checksum)
                   VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET
                     text=excluded.text,vector_json=excluded.vector_json,owner_id=excluded.owner_id,
                     embedding_model=excluded.embedding_model,embedding_version=excluded.embedding_version,
                     dimensions=excluded.dimensions,text_checksum=excluded.text_checksum,updated_at=CURRENT_TIMESTAMP''',
                (row_id, str(memory_id), clean, json.dumps(vector), owner, model, version, len(vector), checksum))
        return {'memory_id': str(memory_id), 'embedding_model': model, 'embedding_version': version, 'dimensions': len(vector), 'text_checksum': checksum}

    def search(self, query: str, limit: int = 8, min_score: float = -1.0, *, owner_id: str | None = None):
        owner = str(owner_id or self.owner_id)
        q = list(map(float, self.embedder(str(query))))
        with self._con() as con:
            rows = con.execute('SELECT * FROM vectors WHERE owner_id=?', (owner,)).fetchall()
        out = []
        for row in rows:
            vector = json.loads(row['vector_json'])
            if len(vector) != len(q):
                continue
            score = cosine(q, vector)
            if score >= min_score:
                out.append({'memory_id': row['memory_id'], 'text': row['text'], 'score': score,
                            'embedding_model': row['embedding_model'], 'embedding_version': row['embedding_version']})
        return sorted(out, key=lambda item: item['score'], reverse=True)[: max(1, min(int(limit), 100))]

    def delete(self, memory_id: str, *, owner_id: str | None = None):
        owner = str(owner_id or self.owner_id)
        with self._con() as con:
            cur = con.execute('DELETE FROM vectors WHERE memory_id=? AND owner_id=?', (str(memory_id), owner))
        return cur.rowcount == 1

    def clear(self, *, owner_id: str | None = None):
        owner = str(owner_id or self.owner_id)
        with self._con() as con:
            cur = con.execute('DELETE FROM vectors WHERE owner_id=?', (owner,))
        return cur.rowcount

    def metadata(self, memory_id: str, *, owner_id: str | None = None):
        owner = str(owner_id or self.owner_id)
        with self._con() as con:
            row = con.execute('SELECT memory_id,owner_id,embedding_model,embedding_version,dimensions,text_checksum,updated_at FROM vectors WHERE memory_id=? AND owner_id=?', (str(memory_id), owner)).fetchone()
        return dict(row) if row else None

    def rebuild(self, memories, *, owner_id: str | None = None):
        owner = str(owner_id or self.owner_id)
        staged = []
        for row in memories:
            if not row or str(row.get('sensitivity') or '').lower() == 'never_store':
                continue
            staged.append((str(row['id']), f"{row.get('subject') or ''}\n{row.get('content') or ''}"))
        self.clear(owner_id=owner)
        for memory_id, text in staged:
            self.upsert(memory_id, text, owner_id=owner)
        return {'owner_id': owner, 'rebuilt': len(staged)}

    def verify(self, canonical_memory_ids, *, owner_id: str | None = None):
        owner = str(owner_id or self.owner_id)
        expected = {str(item) for item in canonical_memory_ids}
        with self._con() as con:
            rows = con.execute('SELECT memory_id,vector_json,dimensions FROM vectors WHERE owner_id=?', (owner,)).fetchall()
        actual = {row['memory_id'] for row in rows}
        corrupt = []
        for row in rows:
            try:
                vector = json.loads(row['vector_json'])
                if not isinstance(vector, list) or (row['dimensions'] is not None and len(vector) != int(row['dimensions'])):
                    corrupt.append(row['memory_id'])
            except Exception:
                corrupt.append(row['memory_id'])
        return {'ok': not corrupt and actual <= expected, 'missing': sorted(expected - actual),
                'orphaned': sorted(actual - expected), 'corrupt': sorted(corrupt)}
