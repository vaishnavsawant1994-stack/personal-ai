from __future__ import annotations

from datetime import datetime, timezone

from future_intelligence.everyday import EverydayIntelligence


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def normalized(rows):
    return {' '.join(str(row['title']).lower().split()) for row in rows}


def test_deterministic_commitment_surfacing_precision_and_recall(tmp_path):
    """Fixed benchmark with labels specified independently of engine output."""
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', clock=Clock(now))

    engine.add('followup', 'Overdue John followup', due_at='2026-09-15T09:00:00+00:00')
    engine.add('commitment', 'Send proposal today', due_at='2026-09-15T11:00:00+00:00')
    engine.add('commitment', 'Unscheduled explicit promise')
    engine.add('followup', 'Future followup', due_at='2026-09-20T09:00:00+00:00')

    completed = engine.add('commitment', 'Completed obligation', due_at='2026-09-15T08:00:00+00:00')
    engine.complete(completed)
    cancelled = engine.add('commitment', 'Cancelled obligation', due_at='2026-09-15T08:00:00+00:00')
    engine.cancel(cancelled)
    superseded = engine.add('commitment', 'Superseded obligation', due_at='2026-09-15T08:00:00+00:00')
    replacement = engine.add('commitment', 'Replacement future obligation', due_at='2026-09-20T08:00:00+00:00')
    engine.supersede(superseded, replacement)

    engine.add('goal', 'Irrelevant goal statement', priority=.9)
    engine.add('commitment', '  Send   proposal   today ', due_at='2026-09-15T11:00:00+00:00', priority=.4)

    expected = {
        'overdue john followup',
        'send proposal today',
        'unscheduled explicit promise',
    }
    actual = normalized(engine.forgotten())
    true_positive = len(actual & expected)
    false_positive = len(actual - expected)
    false_negative = len(expected - actual)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0

    assert actual == expected
    assert precision == 1.0
    assert recall == 1.0
    assert false_positive == 0
    assert false_negative == 0
