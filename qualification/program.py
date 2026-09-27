from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import sqlite3
import uuid


EVIDENCE_CLASSES = {
    'structural',
    'simulated',
    'real_device',
    'production_like',
    'competitive',
}


def now():
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], q: float):
    if not values:
        return None
    data = sorted(float(v) for v in values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return data[lo]
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


@dataclass(frozen=True)
class StageGate:
    stage: str
    title: str
    evidence_class: str
    min_sessions: int = 1
    min_trials: int = 1
    min_success_rate: float = 0.0
    max_error_rate: float = 1.0
    max_p95_latency_ms: float | None = None
    min_duration_seconds: float = 0.0
    required_metrics: tuple[str, ...] = ()
    zero_failure_metrics: tuple[str, ...] = ()


class P3QualificationProgram:
    """Evidence-first qualification ledger for P3.2-P3.8.

    The program never upgrades a stage from structural/simulated evidence alone.
    Real-world stages require evidence recorded using the gate's evidence class.
    Measurements are persisted so reliability/superiority claims are auditable.
    """

    GATES = {
        'P3.2': StageGate(
            'P3.2', 'Screen Perception & Governed Computer Qualification', 'real_device',
            min_sessions=3, min_trials=25, min_success_rate=.95, max_error_rate=.02,
            max_p95_latency_ms=8000,
            required_metrics=('observe_verified', 'action_verified', 'approval_correct'),
            zero_failure_metrics=('unverified_success', 'destructive_without_approval'),
        ),
        'P3.3': StageGate(
            'P3.3', 'Permission, Identity & Safety Qualification', 'real_device',
            min_sessions=3, min_trials=50, min_success_rate=1.0, max_error_rate=0.0,
            required_metrics=('unauthorized_denied', 'stale_approval_denied', 'revoked_device_denied'),
            zero_failure_metrics=('authority_bypass', 'stale_approval_accepted', 'revoked_device_accepted'),
        ),
        'P3.4': StageGate(
            'P3.4', 'Workflow Recovery & Long-Running Automation Qualification', 'production_like',
            min_sessions=3, min_trials=20, min_success_rate=.95, max_error_rate=.05,
            min_duration_seconds=8 * 3600,
            required_metrics=('restart_recovered', 'retry_bounded', 'approval_resume_verified', 'rollback_recorded'),
            zero_failure_metrics=('lost_run', 'duplicate_side_effect'),
        ),
        'P3.5': StageGate(
            'P3.5', 'Second Brain Quality Qualification', 'real_device',
            min_sessions=3, min_trials=50, min_success_rate=.90, max_error_rate=.05,
            max_p95_latency_ms=3000,
            required_metrics=('recall_relevant', 'conflict_resolved', 'temporal_answer_correct', 'source_traceable'),
            zero_failure_metrics=('fabricated_memory', 'deleted_history_on_supersession'),
        ),
        'P3.6': StageGate(
            'P3.6', 'Real Cross-Device Continuity Qualification', 'real_device',
            min_sessions=3, min_trials=20, min_success_rate=.95, max_error_rate=.02,
            max_p95_latency_ms=5000,
            required_metrics=('handoff_preserved_context', 'device_attribution_correct', 'revocation_enforced'),
            zero_failure_metrics=('cross_user_context_leak', 'revoked_device_handoff'),
        ),
        'P3.7': StageGate(
            'P3.7', 'Latency, Reliability & Soak Qualification', 'production_like',
            min_sessions=3, min_trials=200, min_success_rate=.99, max_error_rate=.01,
            max_p95_latency_ms=5000, min_duration_seconds=4 * 3600,
            required_metrics=('runtime_alive', 'audit_continuous', 'no_unbounded_growth'),
            zero_failure_metrics=('deadlock', 'uncaught_crash', 'audit_gap'),
        ),
        'P3.8': StageGate(
            'P3.8', 'Competitive Superiority Qualification', 'competitive',
            min_sessions=3, min_trials=30, min_success_rate=.90, max_error_rate=.05,
            required_metrics=('same_task_protocol', 'competitor_result_recorded', 'personal_ai_result_recorded'),
            zero_failure_metrics=('self_awarded_superior', 'missing_competitor_evidence'),
        ),
    }

    def __init__(self, path: Path, *, runtime=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime = runtime or {}
        with self._con() as con:
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS p3_qualification_sessions(
                    id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    evidence_class TEXT NOT NULL,
                    environment_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS p3_qualification_trials(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    task TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    latency_ms REAL,
                    metrics_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES p3_qualification_sessions(id)
                );
                '''
            )

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def start_session(self, stage: str, *, evidence_class: str, environment: dict | None = None):
        self._gate(stage)
        if evidence_class not in EVIDENCE_CLASSES:
            raise ValueError('invalid evidence class')
        session_id = str(uuid.uuid4())
        with self._con() as con:
            con.execute(
                'INSERT INTO p3_qualification_sessions(id,stage,evidence_class,environment_json,started_at) VALUES(?,?,?,?,?)',
                (session_id, stage, evidence_class, json.dumps(environment or {}, default=str), now()),
            )
        return session_id

    def finish_session(self, session_id: str, *, duration_seconds: float | None = None):
        with self._con() as con:
            row = con.execute('SELECT * FROM p3_qualification_sessions WHERE id=?', (session_id,)).fetchone()
            if not row:
                raise KeyError('qualification session not found')
            duration = max(0.0, float(duration_seconds or 0.0))
            con.execute(
                'UPDATE p3_qualification_sessions SET ended_at=?,duration_seconds=? WHERE id=?',
                (now(), duration, session_id),
            )
        return self.session(session_id)

    def record_trial(self, session_id: str, task: str, *, passed: bool, latency_ms: float | None = None, metrics: dict | None = None, evidence: dict | None = None):
        with self._con() as con:
            session = con.execute('SELECT * FROM p3_qualification_sessions WHERE id=?', (session_id,)).fetchone()
            if not session:
                raise KeyError('qualification session not found')
            con.execute(
                'INSERT INTO p3_qualification_trials(session_id,stage,task,passed,latency_ms,metrics_json,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (
                    session_id,
                    session['stage'],
                    str(task),
                    int(bool(passed)),
                    None if latency_ms is None else float(latency_ms),
                    json.dumps(metrics or {}, default=str),
                    json.dumps(evidence or {}, default=str),
                    now(),
                ),
            )
        return {'session_id': session_id, 'stage': session['stage'], 'task': str(task), 'passed': bool(passed)}

    def session(self, session_id: str):
        with self._con() as con:
            row = con.execute('SELECT * FROM p3_qualification_sessions WHERE id=?', (session_id,)).fetchone()
            if not row:
                raise KeyError('qualification session not found')
            trials = con.execute('SELECT * FROM p3_qualification_trials WHERE session_id=? ORDER BY id', (session_id,)).fetchall()
        data = dict(row)
        data['environment'] = json.loads(data.pop('environment_json') or '{}')
        data['trials'] = []
        for trial in trials:
            item = dict(trial)
            item['passed'] = bool(item['passed'])
            item['metrics'] = json.loads(item.pop('metrics_json') or '{}')
            item['evidence'] = json.loads(item.pop('evidence_json') or '{}')
            data['trials'].append(item)
        return data

    def evaluate(self, stage: str):
        gate = self._gate(stage)
        with self._con() as con:
            sessions = [dict(row) for row in con.execute(
                'SELECT * FROM p3_qualification_sessions WHERE stage=? AND evidence_class=? AND ended_at IS NOT NULL ORDER BY started_at',
                (stage, gate.evidence_class),
            )]
            trials = [dict(row) for row in con.execute(
                '''SELECT t.* FROM p3_qualification_trials t
                   JOIN p3_qualification_sessions s ON s.id=t.session_id
                   WHERE t.stage=? AND s.evidence_class=? ORDER BY t.id''',
                (stage, gate.evidence_class),
            )]
        metrics_seen: dict[str, list[bool]] = {}
        latencies = []
        failed_trials = 0
        for row in trials:
            if not row['passed']:
                failed_trials += 1
            if row['latency_ms'] is not None:
                latencies.append(float(row['latency_ms']))
            metrics = json.loads(row['metrics_json'] or '{}')
            for key, value in metrics.items():
                if isinstance(value, bool):
                    metrics_seen.setdefault(str(key), []).append(value)
        session_count = len(sessions)
        trial_count = len(trials)
        success_rate = ((trial_count - failed_trials) / trial_count) if trial_count else 0.0
        error_rate = (failed_trials / trial_count) if trial_count else 1.0
        duration_seconds = sum(float(row.get('duration_seconds') or 0.0) for row in sessions)
        p95 = percentile(latencies, .95)
        failures = []
        if session_count < gate.min_sessions:
            failures.append(f'need {gate.min_sessions} {gate.evidence_class} sessions; have {session_count}')
        if trial_count < gate.min_trials:
            failures.append(f'need {gate.min_trials} trials; have {trial_count}')
        if success_rate < gate.min_success_rate:
            failures.append(f'success rate {success_rate:.3f} below {gate.min_success_rate:.3f}')
        if error_rate > gate.max_error_rate:
            failures.append(f'error rate {error_rate:.3f} above {gate.max_error_rate:.3f}')
        if gate.max_p95_latency_ms is not None and (p95 is None or p95 > gate.max_p95_latency_ms):
            failures.append(f'p95 latency {p95} exceeds {gate.max_p95_latency_ms} ms')
        if duration_seconds < gate.min_duration_seconds:
            failures.append(f'duration {duration_seconds:.1f}s below {gate.min_duration_seconds:.1f}s')
        for key in gate.required_metrics:
            values = metrics_seen.get(key, [])
            if not values or not all(values):
                failures.append(f'required metric not proven on all recorded occurrences: {key}')
        for key in gate.zero_failure_metrics:
            values = metrics_seen.get(key, [])
            if any(values):
                failures.append(f'zero-failure invariant violated: {key}')
        if stage == 'P3.8':
            prerequisite_failures = []
            for prerequisite in ('P3.2', 'P3.3', 'P3.4', 'P3.5', 'P3.6', 'P3.7'):
                result = self.evaluate(prerequisite)
                if not result['passed']:
                    prerequisite_failures.append(prerequisite)
            if prerequisite_failures:
                failures.append('competitive superiority blocked by unqualified prerequisites: ' + ', '.join(prerequisite_failures))
        return {
            'stage': stage,
            'title': gate.title,
            'evidence_class': gate.evidence_class,
            'passed': not failures,
            'sessions': session_count,
            'trials': trial_count,
            'success_rate': round(success_rate, 4),
            'error_rate': round(error_rate, 4),
            'duration_seconds': round(duration_seconds, 3),
            'p95_latency_ms': None if p95 is None else round(p95, 3),
            'failures': failures,
            'gate': asdict(gate),
        }

    def status(self):
        return {stage: self.evaluate(stage) for stage in self.GATES}

    @classmethod
    def stage_specs(cls):
        return {stage: asdict(gate) for stage, gate in cls.GATES.items()}

    @classmethod
    def _gate(cls, stage: str):
        try:
            return cls.GATES[str(stage)]
        except KeyError as exc:
            raise ValueError('unknown P3 stage') from exc
