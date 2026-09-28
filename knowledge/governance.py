from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

from memory.policy import is_never_store


def _now():
    return datetime.now(timezone.utc).isoformat()


class KnowledgeAuthority:
    """Governance/source facade over the canonical KnowledgeStore.

    It uses the same knowledge SQLite database for source/sync metadata. The
    underlying KnowledgeStore remains canonical document/chunk truth; this
    layer owns source identity, owner/project scope and disconnect visibility.
    """

    CANONICAL_OWNER = 'owner'
    DISCONNECT_POLICIES = {'retain-disabled', 'delete'}

    def __init__(self, store, *, events=None):
        self.store = store
        self.events = events
        with self._con() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS knowledge_sources(
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, project_id TEXT,
                    source_type TEXT NOT NULL, external_ref TEXT NOT NULL, display_name TEXT,
                    status TEXT NOT NULL, sync_status TEXT NOT NULL, disconnect_policy TEXT NOT NULL,
                    last_sync_at TEXT, last_error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(owner_id,source_type,external_ref));
                CREATE INDEX IF NOT EXISTS idx_knowledge_sources_owner_status
                    ON knowledge_sources(owner_id,status,updated_at);
                CREATE TABLE IF NOT EXISTS knowledge_source_documents(
                    source_id TEXT NOT NULL, document_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                    project_id TEXT, source_version TEXT, linked_at TEXT NOT NULL,
                    PRIMARY KEY(source_id,document_id));
                CREATE INDEX IF NOT EXISTS idx_knowledge_source_docs_document
                    ON knowledge_source_documents(document_id,owner_id);
                CREATE TABLE IF NOT EXISTS knowledge_sync_requests(
                    source_id TEXT NOT NULL, request_id TEXT NOT NULL, content_checksum TEXT,
                    document_id TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(source_id,request_id));
                ''')

    def __getattr__(self, name):
        return getattr(self.store, name)

    def _con(self):
        con = sqlite3.connect(self.store.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA busy_timeout=30000')
        return con

    @classmethod
    def _owner(cls, owner_id):
        owner = str(owner_id or '').strip()
        if owner != cls.CANONICAL_OWNER:
            raise PermissionError('Knowledge is scoped to the canonical owner')
        return owner

    def _emit(self, name, **payload):
        if self.events:
            self.events.emit(name, **payload)

    @staticmethod
    def _source_parts(source: str):
        value = str(source or 'owner-upload').strip()[:500]
        if ':' in value:
            source_type, external_ref = value.split(':', 1)
        else:
            source_type, external_ref = value, value
        return source_type[:80] or 'source', external_ref[:500] or value

    @staticmethod
    def _source_id(owner_id: str, source_type: str, external_ref: str):
        value = f'{owner_id}\0{source_type}\0{external_ref}'.encode()
        return 'ksrc_' + hashlib.sha256(value).hexdigest()[:32]

    def ensure_source(self, source: str, *, owner_id: str = CANONICAL_OWNER, project_id: str | None = None,
                      display_name: str | None = None, disconnect_policy: str = 'retain-disabled'):
        owner = self._owner(owner_id)
        if disconnect_policy not in self.DISCONNECT_POLICIES:
            raise ValueError('unsupported knowledge disconnect policy')
        source_type, external_ref = self._source_parts(source)
        source_id = self._source_id(owner, source_type, external_ref)
        stamp = _now()
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('''INSERT INTO knowledge_sources(
                    id,owner_id,project_id,source_type,external_ref,display_name,status,sync_status,
                    disconnect_policy,last_sync_at,last_error_code,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,'connected','idle',?,NULL,NULL,?,?)
                   ON CONFLICT(owner_id,source_type,external_ref) DO UPDATE SET
                     project_id=COALESCE(excluded.project_id,knowledge_sources.project_id),
                     display_name=COALESCE(excluded.display_name,knowledge_sources.display_name),
                     updated_at=excluded.updated_at''',
                (source_id, owner, project_id, source_type, external_ref, display_name, disconnect_policy, stamp, stamp))
        return self.source(source_id, owner_id=owner)

    def source(self, source_id: str, *, owner_id: str = CANONICAL_OWNER):
        owner = self._owner(owner_id)
        with self._con() as con:
            row = con.execute('SELECT * FROM knowledge_sources WHERE id=? AND owner_id=?', (str(source_id), owner)).fetchone()
        return dict(row) if row else None

    def sources(self, *, owner_id: str = CANONICAL_OWNER, limit: int = 100, status: str | None = None):
        owner = self._owner(owner_id)
        bounded = max(1, min(int(limit), 500))
        with self._con() as con:
            if status:
                rows = con.execute('SELECT * FROM knowledge_sources WHERE owner_id=? AND status=? ORDER BY updated_at DESC,id LIMIT ?', (owner, str(status), bounded)).fetchall()
            else:
                rows = con.execute('SELECT * FROM knowledge_sources WHERE owner_id=? ORDER BY updated_at DESC,id LIMIT ?', (owner, bounded)).fetchall()
        return [dict(row) for row in rows]

    def ingest(self, *, owner_id: str = CANONICAL_OWNER, project_id: str | None = None,
               request_id: str | None = None, source_version: str | None = None,
               never_store: bool = False, **kwargs):
        owner = self._owner(owner_id)
        metadata = dict(kwargs.get('metadata') or {})
        if never_store or is_never_store(sensitivity=metadata.get('sensitivity'), metadata=metadata):
            raise PermissionError('NEVER_STORE content cannot be ingested into Knowledge')
        source_value = str(kwargs.get('source') or 'owner-upload')[:500]
        source = self.ensure_source(source_value, owner_id=owner, project_id=project_id,
            display_name=metadata.get('display_name') or kwargs.get('title'),
            disconnect_policy=str(metadata.get('disconnect_policy') or 'retain-disabled'))
        source_id = source['id']
        data = kwargs.get('data') or b''
        checksum = hashlib.sha256(bytes(data)).hexdigest() if isinstance(data, (bytes, bytearray)) else None
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            if request_id:
                replay = con.execute('SELECT * FROM knowledge_sync_requests WHERE source_id=? AND request_id=?', (source_id, str(request_id))).fetchone()
                if replay and replay['status'] == 'completed' and replay['document_id']:
                    return self.detail(replay['document_id'])
                con.execute('''INSERT INTO knowledge_sync_requests(source_id,request_id,content_checksum,document_id,status,created_at,updated_at)
                       VALUES(?,?,?,NULL,'started',?,?) ON CONFLICT(source_id,request_id) DO UPDATE SET updated_at=excluded.updated_at''',
                    (source_id, str(request_id), checksum, _now(), _now()))
            con.execute("UPDATE knowledge_sources SET sync_status='syncing',last_error_code=NULL,updated_at=? WHERE id=?", (_now(), source_id))
        metadata.update({'authorized_owner_id': owner, 'project_id': project_id, 'knowledge_source_id': source_id,
            'source_type': source['source_type'], 'external_ref': source['external_ref'],
            'source_version': source_version or metadata.get('version')})
        kwargs['metadata'] = metadata
        try:
            document = self.store.ingest(**kwargs)
        except Exception as exc:
            with self._con() as con:
                con.execute('BEGIN IMMEDIATE')
                con.execute("UPDATE knowledge_sources SET sync_status='error',last_error_code=?,updated_at=? WHERE id=?", (type(exc).__name__[:120], _now(), source_id))
                if request_id:
                    con.execute("UPDATE knowledge_sync_requests SET status='failed',updated_at=? WHERE source_id=? AND request_id=?", (_now(), source_id, str(request_id)))
            self._emit('knowledge.sync.failed', source_id=source_id, error_code=type(exc).__name__)
            raise
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('''INSERT INTO knowledge_source_documents(source_id,document_id,owner_id,project_id,source_version,linked_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(source_id,document_id) DO UPDATE SET
                     project_id=excluded.project_id,source_version=excluded.source_version,linked_at=excluded.linked_at''',
                (source_id, document['id'], owner, project_id, str(source_version) if source_version is not None else None, _now()))
            con.execute("UPDATE knowledge_sources SET status='connected',sync_status='idle',last_sync_at=?,last_error_code=NULL,updated_at=? WHERE id=?", (_now(), _now(), source_id))
            if request_id:
                con.execute("UPDATE knowledge_sync_requests SET document_id=?,status='completed',updated_at=? WHERE source_id=? AND request_id=?", (document['id'], _now(), source_id, str(request_id)))
        self._emit('knowledge.sync.completed', source_id=source_id, document_id=document['id'])
        return {**document, 'knowledge_source_id': source_id}

    def _visible_document_ids(self, owner_id: str, project_id: str | None = None):
        owner = self._owner(owner_id)
        params = [owner]
        project_clause = ''
        if project_id is not None:
            project_clause = ' AND (m.project_id IS NULL OR m.project_id=?)'
            params.append(str(project_id))
        with self._con() as con:
            rows = con.execute('''SELECT DISTINCT m.document_id FROM knowledge_source_documents m
                   JOIN knowledge_sources s ON s.id=m.source_id WHERE m.owner_id=? AND s.status='connected' ''' + project_clause, params).fetchall()
        return {row['document_id'] for row in rows}

    def search(self, query: str, limit: int = 12, *, owner_id: str = CANONICAL_OWNER,
               project_id: str | None = None, access_classes: set[str] | None = None,
               include_history: bool = False):
        owner = self._owner(owner_id)
        visible = self._visible_document_ids(owner, project_id)
        rows = self.store.search(query, max(20, min(int(limit) * 5, 100)), access_classes=access_classes, include_history=include_history)
        output = []
        for row in rows:
            with self._con() as con:
                mapped = con.execute('SELECT 1 FROM knowledge_source_documents WHERE document_id=? LIMIT 1', (row['document_id'],)).fetchone()
            if mapped and row['document_id'] not in visible:
                continue
            output.append(row)
            if len(output) >= max(1, min(int(limit), 50)):
                break
        return output

    def list(self, query: str = '', limit: int = 100, *, owner_id: str = CANONICAL_OWNER,
             project_id: str | None = None, access_classes: set[str] | None = None,
             include_history: bool = False):
        owner = self._owner(owner_id)
        visible = self._visible_document_ids(owner, project_id)
        rows = self.store.list(query, max(20, min(int(limit) * 5, 500)), access_classes=access_classes, include_history=include_history)
        output = []
        for row in rows:
            with self._con() as con:
                mapped = con.execute('SELECT 1 FROM knowledge_source_documents WHERE document_id=? LIMIT 1', (row['id'],)).fetchone()
            if mapped and row['id'] not in visible:
                continue
            output.append(row)
            if len(output) >= max(1, min(int(limit), 500)):
                break
        return output

    def disconnect_source(self, source_id: str, *, owner_id: str = CANONICAL_OWNER, delete: bool | None = None):
        owner = self._owner(owner_id)
        source = self.source(source_id, owner_id=owner)
        if not source:
            return False
        should_delete = source['disconnect_policy'] == 'delete' if delete is None else bool(delete)
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            doc_ids = [row['document_id'] for row in con.execute('SELECT document_id FROM knowledge_source_documents WHERE source_id=? AND owner_id=?', (source_id, owner))]
            con.execute("UPDATE knowledge_sources SET status='disconnected',sync_status='idle',updated_at=? WHERE id=? AND owner_id=?", (_now(), source_id, owner))
        if should_delete:
            for document_id in doc_ids:
                with self._con() as con:
                    other = con.execute("""SELECT 1 FROM knowledge_source_documents m JOIN knowledge_sources s ON s.id=m.source_id
                           WHERE m.document_id=? AND m.source_id<>? AND s.status='connected' LIMIT 1""", (document_id, source_id)).fetchone()
                if not other:
                    self.store.delete_version(document_id)
        self._emit('knowledge.source.disconnected', source_id=source_id, deleted=should_delete)
        return True

    def delete_version(self, document_id: str):
        deleted = self.store.delete_version(document_id)
        if deleted:
            with self._con() as con:
                con.execute('DELETE FROM knowledge_source_documents WHERE document_id=?', (str(document_id),))
        return deleted

    def delete_lineage(self, lineage_id: str):
        versions = self.store.history(lineage_id)
        ids = [row['id'] for row in versions]
        count = self.store.delete_lineage(lineage_id)
        if ids:
            with self._con() as con:
                con.executemany('DELETE FROM knowledge_source_documents WHERE document_id=?', [(item,) for item in ids])
        return count

    def source_evidence(self, document_id: str, *, owner_id: str = CANONICAL_OWNER):
        owner = self._owner(owner_id)
        with self._con() as con:
            rows = con.execute('''SELECT s.id,s.source_type,s.external_ref,s.display_name,s.status,s.last_sync_at,m.project_id,m.source_version
                   FROM knowledge_source_documents m JOIN knowledge_sources s ON s.id=m.source_id
                   WHERE m.document_id=? AND m.owner_id=? ORDER BY s.updated_at DESC''', (str(document_id), owner)).fetchall()
        return [dict(row) for row in rows]

    def index_status(self, *, owner_id: str = CANONICAL_OWNER):
        owner = self._owner(owner_id)
        visible = self._visible_document_ids(owner)
        with self._con() as con:
            count = 0
            if visible:
                placeholders = ','.join('?' for _ in visible)
                count = con.execute(f'SELECT COUNT(*) AS n FROM knowledge_chunks WHERE document_id IN ({placeholders})', list(visible)).fetchone()['n']
        return {'authority': 'derived_chunks', 'owner_id': owner, 'documents': len(visible), 'chunks': int(count), 'embedding_provider': None}
