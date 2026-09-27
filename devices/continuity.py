from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class ContinuityService:
    """Shared context ledger for one Personal AI across many trusted devices."""

    def __init__(self, path: Path, *, events=None, second_brain=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = events
        self.second_brain = second_brain
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
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def create_thread(self, title: str = 'Current context', *, device_id: str | None = None, context: dict | None = None):
        thread_id = str(uuid.uuid4())
        stamp = now()
        with self._con() as con:
            con.execute(
                'INSERT INTO continuity_threads VALUES(?,?,?,?,?,NULL)',
                (thread_id, str(title), json.dumps(context or {}, default=str), stamp, stamp),
            )
        if device_id:
            self.set_active(device_id, thread_id)
        self._emit('continuity.thread.created', thread_id=thread_id, device_id=device_id, title=title)
        return thread_id

    def set_active(self, device_id: str, thread_id: str):
        if not self.thread(thread_id):
            raise KeyError('continuity thread not found')
        with self._con() as con:
            con.execute(
                '''INSERT INTO continuity_device_state(device_id,active_thread_id,last_event_id,updated_at)
                   VALUES(?,?,0,?)
                   ON CONFLICT(device_id) DO UPDATE SET active_thread_id=excluded.active_thread_id,updated_at=excluded.updated_at''',
                (device_id, thread_id, now()),
            )
        self._emit('continuity.active.changed', device_id=device_id, thread_id=thread_id)
        return {'device_id': device_id, 'thread_id': thread_id}

    def append(self, thread_id: str, *, device_id: str | None, kind: str, payload: dict):
        thread = self.thread(thread_id)
        if not thread or thread.get('closed_at'):
            raise KeyError('active continuity thread not found')
        event_id = str(uuid.uuid4())
        stamp = now()
        with self._con() as con:
            cur = con.execute(
                'INSERT INTO continuity_events(event_id,thread_id,device_id,kind,payload_json,created_at) VALUES(?,?,?,?,?,?)',
                (event_id, thread_id, device_id, str(kind), json.dumps(payload or {}, default=str), stamp),
            )
            sequence = int(cur.lastrowid)
            con.execute('UPDATE continuity_threads SET updated_at=? WHERE id=?', (stamp, thread_id))
        if device_id:
            self.set_active(device_id, thread_id)
        self._emit('continuity.event', thread_id=thread_id, device_id=device_id, kind=kind, sequence=sequence)
        return {'event_id': event_id, 'sequence': sequence, 'thread_id': thread_id}

    def update_context(self, thread_id: str, patch: dict, *, replace: bool = False):
        thread = self.thread(thread_id)
        if not thread:
            raise KeyError('continuity thread not found')
        context = {} if replace else dict(thread['context'])
        context.update(dict(patch or {}))
        with self._con() as con:
            con.execute(
                'UPDATE continuity_threads SET context_json=?,updated_at=? WHERE id=?',
                (json.dumps(context, default=str), now(), thread_id),
            )
        self._emit('continuity.context.updated', thread_id=thread_id, keys=sorted(patch or {}))
        return context

    def thread(self, thread_id: str):
        with self._con() as con:
            row = con.execute('SELECT * FROM continuity_threads WHERE id=?', (thread_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data['context'] = json.loads(data.pop('context_json') or '{}')
        return data

    def latest_thread(self):
        with self._con() as con:
            row = con.execute(
                'SELECT id FROM continuity_threads WHERE closed_at IS NULL ORDER BY updated_at DESC LIMIT 1'
            ).fetchone()
        return self.thread(row['id']) if row else None

    def active_for_device(self, device_id: str):
        with self._con() as con:
            row = con.execute('SELECT active_thread_id FROM continuity_device_state WHERE device_id=?', (device_id,)).fetchone()
        if row and row['active_thread_id']:
            thread = self.thread(row['active_thread_id'])
            if thread and not thread.get('closed_at'):
                return thread
        latest = self.latest_thread()
        if latest:
            self.set_active(device_id, latest['id'])
        return latest

    def resume(self, device_id: str, *, thread_id: str | None = None, event_limit: int = 30):
        thread = self.thread(thread_id) if thread_id else self.active_for_device(device_id)
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
        with self._con() as con:
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

    def sync(self, device_id: str, *, limit: int = 200):
        thread = self.active_for_device(device_id)
        if not thread:
            return self.resume(device_id, event_limit=limit)
        with self._con() as con:
            state = con.execute('SELECT last_event_id FROM continuity_device_state WHERE device_id=?', (device_id,)).fetchone()
        after = int(state['last_event_id']) if state else 0
        events = self.events_for_thread(thread['id'], after_sequence=after, limit=limit)
        if events:
            last = int(events[-1]['sequence'])
            with self._con() as con:
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

    def close_thread(self, thread_id: str):
        with self._con() as con:
            cur = con.execute('UPDATE continuity_threads SET closed_at=?,updated_at=? WHERE id=? AND closed_at IS NULL', (now(), now(), thread_id))
        return cur.rowcount == 1

    def _emit(self, event: str, **payload):
        if self.events:
            self.events.emit(event, **payload)
