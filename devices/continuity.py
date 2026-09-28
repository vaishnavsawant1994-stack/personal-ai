from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


def now():
    return datetime.now(timezone.utc).isoformat()


class ContinuityService:
    """Shared conversation/context ledger for Personal AI across trusted devices."""

    def __init__(self, path: Path, *, events=None, second_brain=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = events
        self.second_brain = second_brain
        self.lock = RLock()
        with self._con() as con:
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS continuity_threads(
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS continuity_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    thread_id TEXT NOT NULL,
                    device_id TEXT,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES continuity_threads(id)
                );
                CREATE TABLE IF NOT EXISTS continuity_device_state(
                    device_id TEXT PRIMARY KEY,
                    active_thread_id TEXT,
                    last_event_id INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_continuity_events_thread ON continuity_events(thread_id,id);
                '''
            )

    def _con(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        return con

    def create_thread(self, title: str = 'Current context', *, device_id: str | None = None, context: dict | None = None):
        thread_id = str(uuid.uuid4())
        stamp = now()
        with self.lock, self._con() as con:
            con.execute(
                'INSERT INTO continuity_threads VALUES(?,?,?,?,?,NULL)',
                (thread_id, str(title), json.dumps(context or {}, default=str), stamp, stamp),
            )
        if device_id:
            self.set_active(device_id, thread_id)
        self._emit('continuity.thread.created', thread_id=thread_id, device_id=device_id, title=title)
        return thread_id

    def list_threads(self, query: str = '', *, limit: int = 50, include_closed: bool = False):
        clauses = []
        params = []
        if not include_closed:
            clauses.append('t.closed_at IS NULL')
        if query.strip():
            term = f'%{query.strip()}%'
            clauses.append('''(t.title LIKE ? OR EXISTS(
                SELECT 1 FROM continuity_events e
                WHERE e.thread_id=t.id AND e.payload_json LIKE ?
            ))''')
            params.extend([term, term])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        params.append(max(1, min(int(limit), 200)))
        with self.lock, self._con() as con:
            rows = con.execute(
                f'''SELECT t.*,
                    (SELECT COUNT(*) FROM continuity_events e WHERE e.thread_id=t.id) AS event_count,
                    (SELECT payload_json FROM continuity_events e WHERE e.thread_id=t.id ORDER BY e.id DESC LIMIT 1) AS latest_payload_json
                    FROM continuity_threads t {where}
                    ORDER BY t.updated_at DESC LIMIT ?''',
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item['context'] = json.loads(item.pop('context_json') or '{}')
            latest_payload = json.loads(item.pop('latest_payload_json') or '{}')
            item['preview'] = str(latest_payload.get('text') or '')[:160]
            output.append(item)
        return output

    def rename_thread(self, thread_id: str, title: str):
        clean = ' '.join(str(title or '').split())[:120]
        if not clean:
            raise ValueError('conversation title is required')
        with self.lock, self._con() as con:
            cur = con.execute(
                'UPDATE continuity_threads SET title=?,updated_at=? WHERE id=? AND closed_at IS NULL',
                (clean, now(), thread_id),
            )
        if cur.rowcount != 1:
            raise KeyError('active continuity thread not found')
        self._emit('continuity.thread.renamed', thread_id=thread_id, title=clean)
        return self.thread(thread_id)

    def set_active(self, device_id: str, thread_id: str, *, authority_guard=None):
        stamp = now()
        with self.lock, self._con() as con:
            # Governed activation is one transaction: validate current authority
            # after BEGIN IMMEDIATE and before any durable continuity mutation.
            con.execute('BEGIN IMMEDIATE')
            if authority_guard is not None:
                authority_guard()
            thread = con.execute(
                'SELECT closed_at FROM continuity_threads WHERE id=?',
                (thread_id,),
            ).fetchone()
            if not thread or thread['closed_at']:
                raise KeyError('active continuity thread not found')
            current = con.execute(
                'SELECT active_thread_id,last_event_id FROM continuity_device_state WHERE device_id=?',
                (device_id,),
            ).fetchone()
            last_event_id = int(current['last_event_id']) if current and current['active_thread_id'] == thread_id else 0
            con.execute(
                '''INSERT INTO continuity_device_state(device_id,active_thread_id,last_event_id,updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(device_id) DO UPDATE SET
                     active_thread_id=excluded.active_thread_id,
                     last_event_id=excluded.last_event_id,
                     updated_at=excluded.updated_at''',
                (device_id, thread_id, last_event_id, stamp),
            )
        self._emit('continuity.active.changed', device_id=device_id, thread_id=thread_id)
        return {'device_id': device_id, 'thread_id': thread_id}

    def append(
        self,
        thread_id: str,
        *,
        device_id: str | None,
        kind: str,
        payload: dict,
        event_id: str | None = None,
    ):
        """Append an event exactly once when a stable event_id is supplied.

        A retry with the same event_id and identical content returns the existing
        sequence without re-emitting the event. Reusing an event_id for different
        content fails closed.
        """
        thread = self.thread(thread_id)
        if not thread or thread.get('closed_at'):
            raise KeyError('active continuity thread not found')
        stable_event_id = str(event_id or uuid.uuid4())
        event_kind = str(kind)
        payload_json = json.dumps(payload or {}, default=str, sort_keys=True)
        stamp = now()
        inserted = False
        with self.lock, self._con() as con:
            cur = con.execute(
                '''INSERT OR IGNORE INTO continuity_events(
                    event_id,thread_id,device_id,kind,payload_json,created_at
                ) VALUES(?,?,?,?,?,?)''',
                (stable_event_id, thread_id, device_id, event_kind, payload_json, stamp),
            )
            if cur.rowcount == 1:
                inserted = True
                sequence = int(cur.lastrowid)
                con.execute('UPDATE continuity_threads SET updated_at=? WHERE id=?', (stamp, thread_id))
            else:
                existing = con.execute(
                    '''SELECT id,thread_id,device_id,kind,payload_json FROM continuity_events
                       WHERE event_id=?''',
                    (stable_event_id,),
                ).fetchone()
                if existing is None:
                    raise RuntimeError('continuity idempotency lookup failed')
                same = (
                    str(existing['thread_id']) == str(thread_id)
                    and (existing['device_id'] or None) == (device_id or None)
                    and str(existing['kind']) == event_kind
                    and str(existing['payload_json']) == payload_json
                )
                if not same:
                    raise ValueError('continuity event_id is already bound to different content')
                sequence = int(existing['id'])
        if inserted:
            if device_id:
                self.set_active(device_id, thread_id)
            self._emit('continuity.event', thread_id=thread_id, device_id=device_id, kind=event_kind, sequence=sequence)
        return {
            'event_id': stable_event_id,
            'sequence': sequence,
            'thread_id': thread_id,
            'duplicate': not inserted,
        }

    def update_context(self, thread_id: str, patch: dict, *, replace: bool = False):
        thread = self.thread(thread_id)
        if not thread:
            raise KeyError('continuity thread not found')
        context = {} if replace else dict(thread['context'])
        context.update(dict(patch or {}))
        with self.lock, self._con() as con:
            con.execute(
                'UPDATE continuity_threads SET context_json=?,updated_at=? WHERE id=?',
                (json.dumps(context, default=str), now(), thread_id),
            )
        self._emit('continuity.context.updated', thread_id=thread_id, keys=sorted(patch or {}))
        return context

    def thread(self, thread_id: str):
        with self.lock, self._con() as con:
            row = con.execute('SELECT * FROM continuity_threads WHERE id=?', (thread_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data['context'] = json.loads(data.pop('context_json') or '{}')
        return data

    def latest_thread(self):
        with self.lock, self._con() as con:
            row = con.execute(
                'SELECT id FROM continuity_threads WHERE closed_at IS NULL ORDER BY updated_at DESC LIMIT 1'
            ).fetchone()
        return self.thread(row['id']) if row else None

    def active_for_device(self, device_id: str, *, authority_guard=None):
        # Governed callers may require current authority even when no device
        # state exists. Check before the fallback can manufacture activation.
        if authority_guard is not None:
            authority_guard()
        with self.lock, self._con() as con:
            row = con.execute('SELECT active_thread_id FROM continuity_device_state WHERE device_id=?', (device_id,)).fetchone()
        if row and row['active_thread_id']:
            thread = self.thread(row['active_thread_id'])
            if thread and not thread.get('closed_at'):
                return thread
        latest = self.latest_thread()
        if latest:
            self.set_active(device_id, latest['id'], authority_guard=authority_guard)
        return latest

    def resume(self, device_id: str, *, thread_id: str | None = None, event_limit: int = 30):
        thread = self.thread(thread_id) if thread_id else self.active_for_device(device_id)
        if thread is not None and thread.get('closed_at'):
            raise KeyError('continuity thread is archived')
        if thread is None:
            created = self.create_thread('Current context', device_id=device_id)
            thread = self.thread(created)
        else:
            self.set_active(device_id, thread['id'])
        events = self.events_for_thread(thread['id'], limit=event_limit)
        memory_context = []
        query = str(thread['context'].get('topic') or thread['title'])
        if self.second_brain and query:
            try:
                memory_context = self.second_brain.context(query, limit=6)
            except Exception:
                pass
        return {'thread': thread, 'events': events, 'memory_context': memory_context}

    def events_for_thread(self, thread_id: str, *, after_sequence: int = 0, limit: int = 100):
        with self.lock, self._con() as con:
            rows = con.execute(
                '''SELECT * FROM continuity_events WHERE thread_id=? AND id>? ORDER BY id ASC LIMIT ?''',
                (thread_id, int(after_sequence), max(1, min(int(limit), 1000))),
            ).fetchall()
        output = []
        for row in rows:
            data = dict(row)
            data['payload'] = json.loads(data.pop('payload_json') or '{}')
            data['sequence'] = data.pop('id')
            output.append(data)
        return output

    def conversation_history(self, thread_id: str, *, limit: int = 16):
        """Return bounded model history from the canonical continuity ledger."""
        bounded = max(1, min(int(limit), 64))
        with self.lock, self._con() as con:
            rows = con.execute(
                '''SELECT kind,payload_json FROM continuity_events
                   WHERE thread_id=? AND kind IN ('user_message','assistant_message')
                   ORDER BY id DESC LIMIT ?''',
                (thread_id, bounded),
            ).fetchall()
        history = []
        for row in reversed(rows):
            payload = json.loads(row['payload_json'] or '{}')
            text = str(payload.get('text') or '').strip()
            if not text:
                continue
            history.append({
                'role': 'user' if row['kind'] == 'user_message' else 'assistant',
                'content': text,
            })
        return history

    def sync(self, device_id: str, *, limit: int = 200, after_sequence: int | None = None):
        thread = self.active_for_device(device_id)
        if not thread:
            return self.resume(device_id, event_limit=limit)
        with self.lock, self._con() as con:
            state = con.execute(
                'SELECT active_thread_id,last_event_id FROM continuity_device_state WHERE device_id=?',
                (device_id,),
            ).fetchone()
        stored_after = int(state['last_event_id']) if state and state['active_thread_id'] == thread['id'] else 0
        requested_after = stored_after if after_sequence is None else max(0, int(after_sequence))
        after = min(requested_after, stored_after) if after_sequence is not None else stored_after
        events = self.events_for_thread(thread['id'], after_sequence=after, limit=limit)
        if events:
            last = int(events[-1]['sequence'])
            with self.lock, self._con() as con:
                con.execute(
                    'UPDATE continuity_device_state SET last_event_id=?,updated_at=? WHERE device_id=?',
                    (last, now(), device_id),
                )
        return {'thread': thread, 'events': events, 'after_sequence': after}

    def handoff(self, thread_id: str, *, from_device: str | None, to_device: str):
        bundle = self.resume(to_device, thread_id=thread_id, event_limit=50)
        self.append(
            thread_id,
            device_id=from_device,
            kind='handoff',
            payload={'from_device': from_device, 'to_device': to_device},
        )
        self._emit('continuity.handoff', thread_id=thread_id, from_device=from_device, to_device=to_device)
        return bundle

    def archive_thread(self, thread_id: str) -> bool:
        stamp = now()
        with self.lock, self._con() as con:
            cur = con.execute(
                'UPDATE continuity_threads SET closed_at=?,updated_at=? WHERE id=? AND closed_at IS NULL',
                (stamp, stamp, thread_id),
            )
            if cur.rowcount:
                con.execute(
                    'UPDATE continuity_device_state SET active_thread_id=NULL,last_event_id=0,updated_at=? WHERE active_thread_id=?',
                    (stamp, thread_id),
                )
        if cur.rowcount:
            self._emit('continuity.thread.archived', thread_id=thread_id)
        return cur.rowcount == 1

    def close_thread(self, thread_id: str):
        return self.archive_thread(thread_id)

    def delete_thread(self, thread_id: str) -> bool:
        with self.lock, self._con() as con:
            if not con.execute('SELECT 1 FROM continuity_threads WHERE id=?', (thread_id,)).fetchone():
                return False
            con.execute(
                'UPDATE continuity_device_state SET active_thread_id=NULL,last_event_id=0,updated_at=? WHERE active_thread_id=?',
                (now(), thread_id),
            )
            con.execute('DELETE FROM continuity_events WHERE thread_id=?', (thread_id,))
            con.execute('DELETE FROM continuity_threads WHERE id=?', (thread_id,))
        self._emit('continuity.thread.deleted', thread_id=thread_id)
        return True

    def export_thread(self, thread_id: str) -> dict:
        thread = self.thread(thread_id)
        if not thread:
            raise KeyError('continuity thread not found')
        return {
            'version': 1,
            'exported_at': now(),
            'conversation': thread,
            'events': self.events_for_thread(thread_id, limit=1000),
        }

    def _emit(self, event: str, **payload):
        if self.events:
            self.events.emit(event, **payload)
