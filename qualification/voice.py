from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import sqlite3
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class VoiceQualificationSummary:
    session_id: str
    evidence_class: str
    turns: int
    barge_trials: int
    barge_successes: int
    barge_success_rate: float | None
    p50_transcript_to_reply_ms: float | None
    p95_transcript_to_reply_ms: float | None
    p50_barge_to_listening_ms: float | None
    p95_barge_to_listening_ms: float | None
    tts_started: int
    tts_completed: int
    tts_errors: int
    errors: int
    passed: bool
    failed_gates: list[str]


class VoiceQualificationRecorder:
    """P3.1 evidence recorder for real or simulated conversational voice trials.

    The recorder listens to the existing EventBus. It never changes voice
    behavior; it records what actually happened so qualification can be based on
    evidence rather than feature presence.
    """

    EVIDENCE_CLASSES = {'structural', 'simulated', 'real_device', 'production_like', 'competitive'}

    def __init__(self, path: Path, events=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = events
        self.session_id: str | None = None
        self._turn = None
        self._barge_started_at = None
        self._init_db()
        if events:
            for name in (
                'voice.transcript', 'voice.reply', 'voice.barge_in', 'voice.turn.cancelled',
                'voice.client.tts_started', 'voice.client.tts_completed', 'voice.client.tts_error',
                'voice.error', 'state',
            ):
                events.subscribe(name, self._on_event)

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self):
        with self._con() as con:
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS voice_qualification_sessions(
                    id TEXT PRIMARY KEY,
                    evidence_class TEXT NOT NULL,
                    environment_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS voice_qualification_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    monotonic_ms REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_voice_qualification_events_session
                ON voice_qualification_events(session_id,id);
                '''
            )

    def start_session(self, *, evidence_class: str, environment: dict | None = None, notes: str = ''):
        normalized = str(evidence_class).strip().lower()
        if normalized not in self.EVIDENCE_CLASSES:
            raise ValueError('invalid evidence class')
        if self.active_session():
            raise RuntimeError('voice qualification session already active')
        session_id = str(uuid.uuid4())
        with self._con() as con:
            con.execute(
                'INSERT INTO voice_qualification_sessions(id,evidence_class,environment_json,started_at,completed_at,notes) VALUES(?,?,?,?,NULL,?)',
                (session_id, normalized, json.dumps(environment or {}, default=str), now(), str(notes or '')),
            )
        self.session_id = session_id
        self._turn = None
        self._barge_started_at = None
        return session_id

    def active_session(self):
        """Return the active session metadata so trusted clients can reconnect safely."""
        with self._con() as con:
            if self.session_id:
                row = con.execute(
                    'SELECT * FROM voice_qualification_sessions WHERE id=? AND completed_at IS NULL',
                    (self.session_id,),
                ).fetchone()
            else:
                row = con.execute(
                    'SELECT * FROM voice_qualification_sessions WHERE completed_at IS NULL ORDER BY started_at DESC LIMIT 1'
                ).fetchone()
        if not row:
            return None
        self.session_id = row['id']
        item = dict(row)
        item['environment'] = json.loads(item.pop('environment_json') or '{}')
        return item

    def stop_session(self):
        if not self.session_id:
            raise RuntimeError('no active voice qualification session')
        session_id = self.session_id
        with self._con() as con:
            con.execute('UPDATE voice_qualification_sessions SET completed_at=? WHERE id=?', (now(), session_id))
        self.session_id = None
        self._turn = None
        self._barge_started_at = None
        return self.summary(session_id)

    def close_active_sessions(self, *, reason: str = 'Owner-confirmed trusted-device takeover'):
        """Close every unfinished session without deleting its retained evidence."""
        completed_at = now()
        with self._con() as con:
            rows = con.execute(
                'SELECT id,notes FROM voice_qualification_sessions WHERE completed_at IS NULL ORDER BY started_at'
            ).fetchall()
            for row in rows:
                existing = str(row['notes'] or '').strip()
                note = f'{existing}\n{reason}'.strip()
                con.execute(
                    'UPDATE voice_qualification_sessions SET completed_at=?,notes=? WHERE id=?',
                    (completed_at, note, row['id']),
                )
        self.session_id = None
        self._turn = None
        self._barge_started_at = None
        return [row['id'] for row in rows]

    def _record(self, event: str, payload: dict):
        if not self.session_id:
            return
        stamp = time.perf_counter() * 1000.0
        with self._con() as con:
            con.execute(
                'INSERT INTO voice_qualification_events(session_id,event,monotonic_ms,payload_json,created_at) VALUES(?,?,?,?,?)',
                (self.session_id, event, stamp, json.dumps(payload, default=str), now()),
            )

    def _on_event(self, event: dict):
        if not self.session_id:
            return
        active = self.active_session()
        if not active:
            return
        expected_device = active.get('environment', {}).get('device_id')
        event_device = event.get('device_id')
        if expected_device and event_device and event_device != expected_device:
            return
        name = str(event.get('event', ''))
        payload = {key: value for key, value in event.items() if key != 'event'}
        self._record(name, payload)
        stamp = time.perf_counter() * 1000.0
        if name == 'voice.transcript':
            self._turn = {'transcript_ms': stamp}
        elif name == 'voice.reply' and self._turn and 'transcript_ms' in self._turn:
            self._record('qualification.transcript_to_reply', {'latency_ms': stamp - self._turn['transcript_ms']})
        elif name == 'voice.barge_in':
            self._barge_started_at = stamp
            self._record('qualification.barge_trial', {})
        elif name == 'state' and str(payload.get('state')) == 'listening' and self._barge_started_at is not None:
            self._record('qualification.barge_to_listening', {'latency_ms': stamp - self._barge_started_at})
            self._record('qualification.barge_success', {})
            self._barge_started_at = None

    @staticmethod
    def _percentile(values: list[float], pct: float):
        if not values:
            return None
        ordered = sorted(values)
        if len(ordered) == 1:
            return round(ordered[0], 3)
        position = (len(ordered) - 1) * pct
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)

    def _events(self, session_id: str):
        with self._con() as con:
            rows = con.execute(
                'SELECT event,payload_json,monotonic_ms,created_at FROM voice_qualification_events WHERE session_id=? ORDER BY id',
                (session_id,),
            ).fetchall()
        return [
            {
                'event': row['event'],
                'payload': json.loads(row['payload_json'] or '{}'),
                'monotonic_ms': row['monotonic_ms'],
                'created_at': row['created_at'],
            }
            for row in rows
        ]

    def summary(self, session_id: str):
        with self._con() as con:
            session = con.execute('SELECT * FROM voice_qualification_sessions WHERE id=?', (session_id,)).fetchone()
        if not session:
            raise KeyError('voice qualification session not found')
        events = self._events(session_id)
        turns = sum(1 for event in events if event['event'] == 'voice.transcript')
        barge_trials = sum(1 for event in events if event['event'] == 'qualification.barge_trial')
        barge_successes = sum(1 for event in events if event['event'] == 'qualification.barge_success')
        transcript_reply = [float(event['payload']['latency_ms']) for event in events if event['event'] == 'qualification.transcript_to_reply']
        barge_listening = [float(event['payload']['latency_ms']) for event in events if event['event'] == 'qualification.barge_to_listening']
        tts_started = sum(1 for event in events if event['event'] == 'voice.client.tts_started')
        tts_completed = sum(1 for event in events if event['event'] == 'voice.client.tts_completed')
        tts_errors = sum(1 for event in events if event['event'] == 'voice.client.tts_error')
        errors = sum(1 for event in events if event['event'] == 'voice.error')
        success_rate = round(barge_successes / barge_trials, 4) if barge_trials else None
        p95_reply = self._percentile(transcript_reply, 0.95)
        p95_barge = self._percentile(barge_listening, 0.95)
        failed = []
        evidence_class = session['evidence_class']
        if evidence_class == 'real_device':
            if turns < 30:
                failed.append('real_device_turns<30')
            if barge_trials < 10:
                failed.append('barge_trials<10')
            if success_rate is None or success_rate < 0.95:
                failed.append('barge_success_rate<0.95')
            if p95_barge is None or p95_barge > 750:
                failed.append('p95_barge_to_listening_ms>750')
            if p95_reply is None or p95_reply > 5000:
                failed.append('p95_transcript_to_reply_ms>5000')
            if errors:
                failed.append('voice_errors>0')
        else:
            if turns < 1:
                failed.append('turns<1')
            if errors:
                failed.append('voice_errors>0')
        result = VoiceQualificationSummary(
            session_id=session_id,
            evidence_class=evidence_class,
            turns=turns,
            barge_trials=barge_trials,
            barge_successes=barge_successes,
            barge_success_rate=success_rate,
            p50_transcript_to_reply_ms=self._percentile(transcript_reply, 0.50),
            p95_transcript_to_reply_ms=p95_reply,
            p50_barge_to_listening_ms=self._percentile(barge_listening, 0.50),
            p95_barge_to_listening_ms=p95_barge,
            tts_started=tts_started,
            tts_completed=tts_completed,
            tts_errors=tts_errors,
            errors=errors,
            passed=not failed,
            failed_gates=failed,
        )
        return asdict(result)

    def sessions(self, limit: int = 50):
        limit = max(1, min(int(limit), 500))
        with self._con() as con:
            rows = con.execute(
                'SELECT * FROM voice_qualification_sessions ORDER BY started_at DESC LIMIT ?',
                (limit,),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item['environment'] = json.loads(item.pop('environment_json') or '{}')
            output.append(item)
        return output
