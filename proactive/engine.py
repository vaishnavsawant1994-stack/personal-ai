from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AttentionDecision:
    action: str
    score: float
    reason: str
    fingerprint: str
    message: str = ''
    source: str = 'unknown'
    suppressed: bool = False


class AttentionRelevanceEngine:
    """Calm proactive intelligence with explicit interruption limits.

    External integrations feed normalized events into consider(). The engine can
    ignore, remember, suggest or notify. It never directly performs consequential
    external actions; those remain routed through the existing tool/approval layer.
    """

    def __init__(
        self,
        path: Path,
        *,
        events=None,
        second_brain=None,
        enabled: bool = True,
        interruptions_per_hour: int = 3,
        default_cooldown_seconds: int = 1800,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = events
        self.second_brain = second_brain
        self.enabled = bool(enabled)
        self.interruptions_per_hour = max(0, int(interruptions_per_hour))
        self.default_cooldown_seconds = max(0, int(default_cooldown_seconds))
        with self._con() as con:
            con.execute(
                '''CREATE TABLE IF NOT EXISTS attention_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL,
                    source TEXT NOT NULL,
                    action TEXT NOT NULL,
                    score REAL NOT NULL,
                    reason TEXT NOT NULL,
                    message TEXT,
                    suppressed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    created_ts REAL NOT NULL
                )'''
            )
            con.execute('CREATE INDEX IF NOT EXISTS idx_attention_fingerprint ON attention_log(fingerprint,created_ts)')

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _fingerprint(source: str, payload: dict[str, Any]) -> str:
        stable = {
            'source': source,
            'kind': payload.get('kind'),
            'id': payload.get('id') or payload.get('event_id') or payload.get('task_id'),
            'subject': payload.get('subject') or payload.get('title') or payload.get('url'),
            'key': payload.get('key'),
        }
        raw = json.dumps(stable, sort_keys=True, default=str).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()[:24]

    @staticmethod
    def _bounded(value, default=0.0):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return float(default)

    def _score(self, source: str, payload: dict[str, Any], context: dict[str, Any] | None = None):
        context = context or {}
        urgency = self._bounded(payload.get('urgency'), 0.0)
        importance = self._bounded(payload.get('importance'), 0.35)
        confidence = self._bounded(payload.get('confidence'), 0.8)
        score = urgency * 0.45 + importance * 0.30 + confidence * 0.10
        reasons = []
        if urgency:
            reasons.append(f'urgency={urgency:.2f}')
        if importance:
            reasons.append(f'importance={importance:.2f}')
        kind = str(payload.get('kind', '')).lower()
        if payload.get('overdue'):
            score += 0.25
            reasons.append('overdue')
        if payload.get('changed') and kind in {'monitor', 'website', 'file', 'project'}:
            score += 0.20
            reasons.append('monitored change')
        if payload.get('needs_approval'):
            score += 0.25
            reasons.append('needs approval')
        if payload.get('failed') or kind in {'failure', 'error'}:
            score += 0.20
            reasons.append('failure')
        due_minutes = payload.get('due_in_minutes')
        try:
            due_minutes = float(due_minutes)
            if due_minutes <= 15:
                score += 0.25
                reasons.append('due within 15 minutes')
            elif due_minutes <= 60:
                score += 0.15
                reasons.append('due within one hour')
        except (TypeError, ValueError):
            pass
        if payload.get('blocked'):
            score += 0.15
            reasons.append('blocked')
        if payload.get('user_active') is False and score < 0.75:
            score -= 0.08
            reasons.append('user inactive; defer low-priority interruption')
        if context.get('focus_mode') and score < 0.9:
            score -= 0.20
            reasons.append('focus mode')
        return max(0.0, min(1.0, score)), ', '.join(reasons) or 'low-signal event'

    def _recent_same(self, fingerprint: str, cooldown_seconds: int, now_ts: float):
        if cooldown_seconds <= 0:
            return False
        with self._con() as con:
            row = con.execute(
                'SELECT created_ts FROM attention_log WHERE fingerprint=? AND action IN (\'suggest\',\'notify\') AND suppressed=0 ORDER BY created_ts DESC LIMIT 1',
                (fingerprint,),
            ).fetchone()
        return bool(row and now_ts - float(row['created_ts']) < cooldown_seconds)

    def _budget_used(self, now_ts: float):
        with self._con() as con:
            row = con.execute(
                'SELECT COUNT(*) AS n FROM attention_log WHERE action IN (\'suggest\',\'notify\') AND suppressed=0 AND created_ts>=?',
                (now_ts - 3600.0,),
            ).fetchone()
        return int(row['n']) if row else 0

    @staticmethod
    def _message(source: str, payload: dict[str, Any]):
        return str(
            payload.get('message')
            or payload.get('summary')
            or payload.get('title')
            or payload.get('subject')
            or f'Personal AI noticed a relevant {source} event.'
        )

    def consider(
        self,
        source: str,
        payload: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
        now_ts: float | None = None,
    ) -> AttentionDecision:
        now_ts = time.time() if now_ts is None else float(now_ts)
        source = str(source or 'unknown')
        payload = dict(payload or {})
        fingerprint = self._fingerprint(source, payload)
        score, reason = self._score(source, payload, context)
        message = self._message(source, payload)
        if not self.enabled:
            decision = AttentionDecision('ignore', score, 'proactive intelligence disabled', fingerprint, message, source, True)
            return self._record(decision, now_ts)
        if score < 0.35:
            action = 'ignore'
        elif score < 0.55:
            action = 'remember'
        elif score < 0.78:
            action = 'suggest'
        else:
            action = 'notify'
        cooldown = int(payload.get('cooldown_seconds', self.default_cooldown_seconds))
        suppressed = False
        if action in {'suggest', 'notify'}:
            if self._recent_same(fingerprint, cooldown, now_ts):
                suppressed = True
                reason += '; duplicate cooldown'
            elif self.interruptions_per_hour <= self._budget_used(now_ts):
                suppressed = True
                reason += '; hourly interruption budget exhausted'
        decision = AttentionDecision(action, score, reason, fingerprint, message, source, suppressed)
        decision = self._record(decision, now_ts)
        self._dispatch(decision, payload)
        return decision

    def _record(self, decision: AttentionDecision, now_ts: float):
        with self._con() as con:
            con.execute(
                'INSERT INTO attention_log(fingerprint,source,action,score,reason,message,suppressed,created_at,created_ts) VALUES(?,?,?,?,?,?,?,?,?)',
                (
                    decision.fingerprint,
                    decision.source,
                    decision.action,
                    float(decision.score),
                    decision.reason,
                    decision.message,
                    int(decision.suppressed),
                    utc_now(),
                    now_ts,
                ),
            )
        return decision

    def _dispatch(self, decision: AttentionDecision, payload: dict[str, Any]):
        if decision.suppressed or decision.action == 'ignore':
            if self.events:
                self.events.emit('proactive.suppressed' if decision.suppressed else 'proactive.ignored', **asdict(decision))
            return
        if decision.action == 'remember' and self.second_brain and payload.get('memory_candidate'):
            try:
                candidate = payload['memory_candidate']
                from memory.second_brain import MemoryCandidate

                self.second_brain.remember(
                    MemoryCandidate(
                        type=str(candidate.get('type', 'event')),
                        subject=str(candidate.get('subject', decision.source)),
                        content=str(candidate.get('content', decision.message)),
                        confidence=self._bounded(candidate.get('confidence'), decision.score),
                        source=str(candidate.get('source', f'proactive:{decision.source}')),
                        verified=bool(candidate.get('verified', False)),
                        tags=list(candidate.get('tags') or []),
                    )
                )
            except Exception:
                pass
        if self.events:
            self.events.emit(f'proactive.{decision.action}', **asdict(decision), payload=payload)

    def history(self, limit: int = 100):
        limit = max(1, min(int(limit), 1000))
        with self._con() as con:
            return [dict(row) for row in con.execute('SELECT * FROM attention_log ORDER BY id DESC LIMIT ?', (limit,))]
