from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timezone
import json
import re
import sqlite3
from pathlib import Path
from typing import Iterable
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _utc_now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Goal:
    id: str
    title: str
    status: str
    priority: float
    due_at: str | None
    context: str


class EverydayIntelligence:
    """P4 daily operating layer over deterministic durable commitment state.

    ``everyday_items`` is the authoritative P4 lifecycle store. It never delegates
    due/completion/permission decisions to an LLM. Real delivery is deliberately
    separate from lifecycle/surfacing state.
    """

    KINDS = {'goal', 'reminder', 'followup', 'task', 'commitment'}
    ACTIVE_STATES = {'created', 'scheduled', 'due', 'surfaced', 'snoozed'}
    TERMINAL_STATES = {'completed', 'dismissed', 'cancelled', 'superseded'}
    DATE_ONLY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    TRANSITION_FIELDS = frozenset({
        'status', 'updated_at', 'due_at', 'timezone', 'snoozed_until', 'surfaced_at',
        'completed_at', 'dismissed_at', 'cancelled_at', 'superseded_by', 'last_surface_key',
    })

    def __init__(
        self,
        path: Path,
        *,
        memory=None,
        second_brain=None,
        proactive=None,
        continuity=None,
        integrations=None,
        events=None,
        clock=None,
        timezone_name: str = 'UTC',
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.memory = memory
        self.second_brain = second_brain
        self.proactive = proactive
        self.continuity = continuity
        self.integrations = integrations
        self.events = events
        self.clock = clock or _utc_now
        self.timezone_name = self._validate_timezone(timezone_name)
        self._init()

    @staticmethod
    def _validate_timezone(value: str):
        name = str(value or 'UTC').strip() or 'UTC'
        try:
            ZoneInfo(name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f'unknown timezone: {name}') from exc
        return name

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        with self._con() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS everyday_items(
              id TEXT PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL,status TEXT NOT NULL,
              priority REAL NOT NULL,due_at TEXT,context TEXT NOT NULL,source TEXT NOT NULL,
              created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_everyday_kind_status ON everyday_items(kind,status);
            CREATE TABLE IF NOT EXISTS everyday_audit(
              id TEXT PRIMARY KEY,item_id TEXT NOT NULL,action TEXT NOT NULL,
              from_status TEXT,to_status TEXT,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_everyday_audit_item ON everyday_audit(item_id,created_at);
            ''')
            columns = {row['name'] for row in c.execute('PRAGMA table_info(everyday_items)')}
            additions = {
                'timezone': "TEXT NOT NULL DEFAULT 'UTC'",
                'snoozed_until': 'TEXT',
                'surfaced_at': 'TEXT',
                'completed_at': 'TEXT',
                'dismissed_at': 'TEXT',
                'cancelled_at': 'TEXT',
                'superseded_by': 'TEXT',
                'related_memory_ids_json': "TEXT NOT NULL DEFAULT '[]'",
                'evidence_json': "TEXT NOT NULL DEFAULT '[]'",
                'surface_count': 'INTEGER NOT NULL DEFAULT 0',
                'last_surface_key': 'TEXT',
            }
            for name, definition in additions.items():
                if name not in columns:
                    c.execute(f'ALTER TABLE everyday_items ADD COLUMN {name} {definition}')
            c.execute("""
                UPDATE everyday_items
                   SET status=CASE WHEN due_at IS NULL OR trim(due_at)='' THEN 'created' ELSE 'scheduled' END
                 WHERE lower(status) IN ('open','pending')
            """)
            c.execute('CREATE INDEX IF NOT EXISTS idx_everyday_due ON everyday_items(status,due_at,snoozed_until)')

    def _now_dt(self, now=None):
        value = self.clock() if now is None else now
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not isinstance(value, datetime):
            raise TypeError('now must be an aware datetime or ISO timestamp')
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _decode_list(value):
        if isinstance(value, list):
            return value
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []

    def _parse_due(self, value: str | None, timezone_name: str | None = None):
        raw = str(value or '').strip()
        if not raw:
            return None, False
        tz = ZoneInfo(self._validate_timezone(timezone_name or self.timezone_name))
        if self.DATE_ONLY.fullmatch(raw):
            day = date.fromisoformat(raw)
            return datetime.combine(day, dt_time.min, tzinfo=tz).astimezone(timezone.utc), True
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(timezone.utc), False

    def _row(self, row):
        if row is None:
            return None
        item = dict(row)
        item['related_memory_ids'] = self._decode_list(item.pop('related_memory_ids_json', '[]'))
        item['evidence'] = self._decode_list(item.pop('evidence_json', '[]'))
        return item

    def _audit(self, item_id, action, from_status=None, to_status=None, metadata=None, *, now=None):
        stamp = self._iso(self._now_dt(now))
        safe = dict(metadata or {})
        with self._con() as c:
            c.execute(
                'INSERT INTO everyday_audit VALUES(?,?,?,?,?,?,?)',
                (str(uuid.uuid4()), item_id, action, from_status, to_status, json.dumps(safe, default=str, sort_keys=True), stamp),
            )
        if self.memory is not None:
            try:
                self.memory.audit('everyday', action, {
                    'item_id': item_id,
                    'from_status': from_status,
                    'to_status': to_status,
                    **safe,
                })
            except Exception:
                pass

    def _existing_memory_ids(self, values: Iterable[str] | None):
        output = []
        seen = set()
        for value in values or []:
            memory_id = str(value or '').strip()
            if not memory_id or memory_id in seen:
                continue
            if self.second_brain is not None:
                try:
                    if not self.second_brain.store.get(memory_id):
                        continue
                except Exception:
                    continue
            output.append(memory_id)
            seen.add(memory_id)
        return output[:100]

    def add(
        self,
        kind: str,
        title: str,
        *,
        priority: float = .5,
        due_at: str | None = None,
        context: str = '',
        source: str = 'user',
        timezone_name: str | None = None,
        related_memory_ids: Iterable[str] | None = None,
        evidence: list | None = None,
        now=None,
    ):
        kind = str(kind or '').strip().lower()
        if kind not in self.KINDS:
            raise ValueError('unsupported everyday item')
        title = str(title or '').strip()
        if not title:
            raise ValueError('title required')
        tz_name = self._validate_timezone(timezone_name or self.timezone_name)
        if due_at:
            self._parse_due(due_at, tz_name)
            status = 'scheduled'
        else:
            status = 'created'
        item_id = str(uuid.uuid4())
        stamp = self._iso(self._now_dt(now))
        related = self._existing_memory_ids(related_memory_ids)
        with self._con() as c:
            c.execute(
                '''INSERT INTO everyday_items(
                    id,kind,title,status,priority,due_at,context,source,created_at,updated_at,timezone,
                    snoozed_until,surfaced_at,completed_at,dismissed_at,cancelled_at,superseded_by,
                    related_memory_ids_json,evidence_json,surface_count,last_surface_key)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    item_id, kind, title, status, max(0.0, min(float(priority), 1.0)),
                    str(due_at) if due_at else None, str(context or ''), str(source or 'user'), stamp, stamp, tz_name,
                    None, None, None, None, None, None, json.dumps(related), json.dumps(evidence or [], default=str), 0, None,
                ),
            )
        self._audit(item_id, 'created', None, status, {'kind': kind, 'has_due': bool(due_at)}, now=now)
        if self.events:
            self.events.emit('everyday.item.created', item_id=item_id, kind=kind, status=status)
        return item_id

    def get(self, item_id: str):
        with self._con() as c:
            return self._row(c.execute('SELECT * FROM everyday_items WHERE id=?', (item_id,)).fetchone())

    def history(self, item_id: str, limit=100):
        with self._con() as c:
            rows = c.execute(
                'SELECT * FROM everyday_audit WHERE item_id=? ORDER BY created_at DESC LIMIT ?',
                (item_id, max(1, min(int(limit), 500))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['metadata'] = json.loads(item.pop('metadata_json') or '{}')
            result.append(item)
        return result

    def items(self, *, status='open', kind: str | None = None, limit=100):
        clauses = []
        params = []
        normalized = str(status or '').strip().lower()
        if normalized == 'open':
            marks = ','.join('?' * len(self.ACTIVE_STATES))
            clauses.append(f'status IN ({marks})')
            params.extend(sorted(self.ACTIVE_STATES))
        elif normalized and normalized != 'all':
            clauses.append('status=?')
            params.append(normalized)
        if kind:
            clauses.append('kind=?')
            params.append(str(kind).strip().lower())
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        params.append(max(1, min(int(limit), 1000)))
        with self._con() as c:
            rows = c.execute(
                f"SELECT * FROM everyday_items{where} ORDER BY priority DESC,COALESCE(snoozed_until,due_at,'9999') ASC,created_at ASC LIMIT ?",
                params,
            ).fetchall()
        return [self._row(row) for row in rows]

    def _due_state(self, item: dict, now_dt: datetime):
        raw = item.get('snoozed_until') if item.get('status') == 'snoozed' and item.get('snoozed_until') else item.get('due_at')
        if not raw:
            return False, False, None
        due_dt, date_only = self._parse_due(raw, item.get('timezone') or self.timezone_name)
        local_now = now_dt.astimezone(ZoneInfo(item.get('timezone') or self.timezone_name))
        if date_only:
            due_day = date.fromisoformat(str(raw))
            return local_now.date() >= due_day, local_now.date() > due_day, due_dt
        return now_dt >= due_dt, now_dt > due_dt, due_dt

    def refresh_due(self, *, now=None):
        now_dt = self._now_dt(now)
        changed = []
        for item in self.items(status='open', limit=1000):
            if item['status'] in {'due', 'surfaced'}:
                continue
            due, _, _ = self._due_state(item, now_dt)
            if not due:
                continue
            old = item['status']
            stamp = self._iso(now_dt)
            with self._con() as c:
                c.execute("UPDATE everyday_items SET status='due',updated_at=? WHERE id=? AND status=?", (stamp, item['id'], old))
            self._audit(item['id'], 'became_due', old, 'due', {'kind': item['kind']}, now=now_dt)
            changed.append(item['id'])
        return changed

    def due_items(self, *, now=None, include_surfaced=False, limit=100):
        now_dt = self._now_dt(now)
        self.refresh_due(now=now_dt)
        states = {'due', 'surfaced'} if include_surfaced else {'due'}
        output = []
        for item in self.items(status='all', limit=1000):
            if item['status'] not in states:
                continue
            due, overdue, due_dt = self._due_state(item, now_dt)
            if not due:
                continue
            output.append({**item, 'overdue': bool(overdue), 'effective_due_at': self._iso(due_dt) if due_dt else None})
        output.sort(key=lambda item: (not item['overdue'], item.get('effective_due_at') or '', -float(item.get('priority') or 0)))
        return output[: max(1, min(int(limit), 500))]

    def surface_due(self, *, now=None, limit=100):
        now_dt = self._now_dt(now)
        surfaced = []
        for item in self.due_items(now=now_dt, include_surfaced=False, limit=limit):
            raw_due = item.get('snoozed_until') or item.get('due_at') or ''
            surface_key = f"{item['id']}:{raw_due}"
            if item.get('last_surface_key') == surface_key:
                continue
            stamp = self._iso(now_dt)
            with self._con() as c:
                changed = c.execute(
                    """UPDATE everyday_items
                          SET status='surfaced',surfaced_at=?,surface_count=surface_count+1,last_surface_key=?,updated_at=?
                        WHERE id=? AND status='due'""",
                    (stamp, surface_key, stamp, item['id']),
                ).rowcount
            if not changed:
                continue
            self._audit(item['id'], 'surfaced', 'due', 'surfaced', {'kind': item['kind'], 'surface_key': surface_key}, now=now_dt)
            if self.events:
                self.events.emit('everyday.item.surfaced', item_id=item['id'], kind=item['kind'], overdue=item['overdue'])
            surfaced.append(self.get(item['id']))
        return surfaced

    def _transition(self, item_id: str, to_status: str, *, action: str, now=None, extra_updates=None, allowed_from=None):
        item = self.get(item_id)
        if not item:
            return False
        if allowed_from is not None and item['status'] not in set(allowed_from):
            return False
        if item['status'] in self.TERMINAL_STATES and to_status not in self.TERMINAL_STATES:
            return False
        stamp = self._iso(self._now_dt(now))
        updates = {'status': to_status, 'updated_at': stamp, **dict(extra_updates or {})}
        unknown = set(updates) - self.TRANSITION_FIELDS
        if unknown:
            raise ValueError(f'invalid everyday transition fields: {sorted(unknown)}')
        query = ','.join(f'{key}=?' for key in updates)
        with self._con() as c:
            changed = c.execute(f'UPDATE everyday_items SET {query} WHERE id=?', [*updates.values(), item_id]).rowcount
        if not changed:
            return False
        self._audit(item_id, action, item['status'], to_status, {'kind': item['kind']}, now=stamp)
        return True

    def snooze(self, item_id: str, until: str, *, timezone_name: str | None = None, now=None):
        item = self.get(item_id)
        if not item or item['status'] in self.TERMINAL_STATES:
            return False
        tz_name = self._validate_timezone(timezone_name or item.get('timezone') or self.timezone_name)
        self._parse_due(until, tz_name)
        return self._transition(item_id, 'snoozed', action='snoozed', now=now, extra_updates={'snoozed_until': str(until), 'timezone': tz_name}, allowed_from=self.ACTIVE_STATES)

    def reschedule(self, item_id: str, due_at: str, *, timezone_name: str | None = None, now=None):
        item = self.get(item_id)
        if not item or item['status'] in self.TERMINAL_STATES:
            return False
        tz_name = self._validate_timezone(timezone_name or item.get('timezone') or self.timezone_name)
        self._parse_due(due_at, tz_name)
        return self._transition(item_id, 'scheduled', action='rescheduled', now=now, extra_updates={'due_at': str(due_at), 'timezone': tz_name, 'snoozed_until': None, 'surfaced_at': None, 'last_surface_key': None}, allowed_from=self.ACTIVE_STATES)

    def complete(self, item_id: str, *, now=None):
        stamp = self._iso(self._now_dt(now))
        return self._transition(item_id, 'completed', action='completed', now=stamp, extra_updates={'completed_at': stamp}, allowed_from=self.ACTIVE_STATES)

    def dismiss(self, item_id: str, *, now=None):
        stamp = self._iso(self._now_dt(now))
        return self._transition(item_id, 'dismissed', action='dismissed', now=stamp, extra_updates={'dismissed_at': stamp}, allowed_from=self.ACTIVE_STATES)

    def cancel(self, item_id: str, *, now=None):
        stamp = self._iso(self._now_dt(now))
        return self._transition(item_id, 'cancelled', action='cancelled', now=stamp, extra_updates={'cancelled_at': stamp}, allowed_from=self.ACTIVE_STATES)

    def supersede(self, older_id: str, newer_id: str, *, now=None):
        if older_id == newer_id or not self.get(newer_id):
            return False
        return self._transition(older_id, 'superseded', action='superseded', now=now, extra_updates={'superseded_by': newer_id}, allowed_from=self.ACTIVE_STATES)

    def _is_future(self, item: dict, now_dt: datetime):
        raw = item.get('snoozed_until') if item.get('status') == 'snoozed' and item.get('snoozed_until') else item.get('due_at')
        if not raw:
            return False
        due, _, _ = self._due_state(item, now_dt)
        return not due

    def attention(self, *, now=None):
        now_dt = self._now_dt(now)
        self.refresh_due(now=now_dt)
        rows = self.items(status='open', limit=100)
        return [row for row in rows if row['status'] in {'due', 'surfaced'} or float(row.get('priority') or 0) >= .7]

    def forgotten(self, *, now=None):
        now_dt = self._now_dt(now)
        self.refresh_due(now=now_dt)
        candidates = []
        for row in self.items(status='open', limit=500):
            if row['kind'] not in {'commitment', 'followup'}:
                continue
            if self._is_future(row, now_dt):
                continue
            candidates.append(row)
        output = []
        seen = set()
        for row in sorted(candidates, key=lambda item: (-float(item.get('priority') or 0), item.get('created_at') or '')):
            key = (' '.join(str(row.get('title') or '').lower().split()), ' '.join(str(row.get('context') or '').lower().split()))
            if key in seen:
                continue
            seen.add(key)
            output.append(row)
        return output

    def today_items(self, *, now=None, limit=100):
        now_dt = self._now_dt(now)
        output = []
        for row in self.items(status='open', limit=500):
            raw = row.get('snoozed_until') if row.get('status') == 'snoozed' and row.get('snoozed_until') else row.get('due_at')
            if not raw:
                continue
            tz = ZoneInfo(row.get('timezone') or self.timezone_name)
            if self.DATE_ONLY.fullmatch(str(raw)):
                due_day = date.fromisoformat(str(raw))
            else:
                due_dt, _ = self._parse_due(raw, row.get('timezone') or self.timezone_name)
                due_day = due_dt.astimezone(tz).date()
            if now_dt.astimezone(tz).date() == due_day:
                output.append(row)
        return output[: max(1, min(int(limit), 500))]

    def overdue_followups(self, *, now=None, limit=100):
        return [row for row in self.due_items(now=now, include_surfaced=True, limit=500) if row['kind'] == 'followup' and row['overdue']][:limit]

    def context_for_item(self, item_id: str, *, allowed_sensitivities: set[str] | None = None):
        item = self.get(item_id)
        if not item or self.second_brain is None:
            return []
        allowed = {'normal'} if allowed_sensitivities is None else {str(value).strip().lower() for value in allowed_sensitivities}
        output = []
        for memory_id in item.get('related_memory_ids', []):
            detail = self.second_brain.memory_detail(memory_id)
            if not detail:
                continue
            sensitivity = str(detail.get('sensitivity') or 'normal').strip().lower()
            if sensitivity == 'never_store' or sensitivity not in allowed:
                continue
            output.append(detail)
        return output

    def briefing(self, *, now=None, allowed_sensitivities: set[str] | None = None):
        now_dt = self._now_dt(now)
        self.refresh_due(now=now_dt)
        open_items = self.items(status='open', limit=100)
        attention = self.attention(now=now_dt)
        forgotten = self.forgotten(now=now_dt)
        today = self.today_items(now=now_dt, limit=100)
        overdue = self.overdue_followups(now=now_dt, limit=100)
        memories = []
        allowed = {'normal'} if allowed_sensitivities is None else allowed_sensitivities
        if self.second_brain:
            try:
                memories = self.second_brain.context('', limit=8, allowed_sensitivities=set(allowed), current_only=True, max_context_chars=12000)
            except TypeError:
                memories = self.second_brain.context('', limit=8, allowed_sensitivities=set(allowed))
            except Exception:
                memories = []
        integration_state = []
        if self.integrations:
            try:
                integration_state = self.integrations.list()
            except Exception:
                integration_state = []
        return {
            'generated_at': self._iso(now_dt),
            'top_priorities': open_items[:5],
            'needs_attention': attention[:10],
            'possible_forgotten_commitments': forgotten[:10],
            'todays_commitments': today[:10],
            'overdue_followups': overdue[:10],
            'relevant_memory': memories,
            'connected_services': integration_state,
            'counts': {'open': len(open_items), 'attention': len(attention), 'followups': len(forgotten), 'today': len(today), 'overdue': len(overdue)},
        }

    def context_switch(self, device_id: str, *, topic: str, surface: str = 'personal-ai'):
        if not self.continuity:
            return {'device_id': device_id, 'topic': topic, 'surface': surface}
        bundle = self.continuity.resume(device_id)
        thread = bundle['thread']
        context = self.continuity.update_context(thread['id'], {'topic': topic, 'surface': surface, 'switched_at': self._iso(self._now_dt())})
        if self.events:
            self.events.emit('context.switched', device_id=device_id, thread_id=thread['id'], topic=topic)
        return {'thread_id': thread['id'], 'context': context}

    def safe_status(self, *, now=None):
        now_dt = self._now_dt(now)
        self.refresh_due(now=now_dt)
        active = self.items(status='open', limit=1000)
        due = self.due_items(now=now_dt, include_surfaced=True, limit=1000)
        terminal = self.items(status='all', limit=1000)
        return {
            'active': len(active),
            'due_or_surfaced': len(due),
            'completed': sum(1 for row in terminal if row['status'] == 'completed'),
            'cancelled_or_superseded': sum(1 for row in terminal if row['status'] in {'cancelled', 'superseded'}),
            'generated_at': self._iso(now_dt),
        }
