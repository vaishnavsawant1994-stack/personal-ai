from __future__ import annotations

from datetime import datetime, timezone
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from future_intelligence.everyday import EverydayIntelligence
from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore
from server.everyday_intelligence_api import everyday_intelligence_router


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value

    def set(self, value):
        self.value = value


class Registry:
    def authenticate(self, device_id, token):
        return device_id == 'dev-1' and token == 'token-1'

    def authorize(self, device_id, scope):
        return device_id == 'dev-1' and scope in {'ai:chat', 'memory:read'}


def test_exact_due_surface_is_idempotent_across_restart(tmp_path):
    clock = Clock(datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc))
    path = tmp_path / 'everyday.sqlite3'
    engine = EverydayIntelligence(path, clock=clock)
    item_id = engine.add('reminder', 'Send document', due_at='2026-09-15T12:05:00+00:00')
    assert engine.get(item_id)['status'] == 'scheduled'
    assert engine.due_items() == []

    clock.set(datetime(2026, 9, 15, 12, 5, tzinfo=timezone.utc))
    assert [row['id'] for row in engine.due_items()] == [item_id]
    first = engine.surface_due()
    assert [row['id'] for row in first] == [item_id]
    assert engine.surface_due() == []

    restarted = EverydayIntelligence(path, clock=clock)
    assert restarted.get(item_id)['status'] == 'surfaced'
    assert restarted.surface_due() == []
    assert restarted.get(item_id)['surface_count'] == 1


def test_snooze_reschedule_completion_cancellation_and_dismissal(tmp_path):
    clock = Clock(datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc))
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', clock=clock)

    reminder = engine.add('reminder', 'Call John', due_at='2026-09-15T11:00:00+00:00')
    engine.refresh_due()
    assert engine.get(reminder)['status'] == 'due'
    assert engine.snooze(reminder, '2026-09-15T13:00:00+00:00')
    assert engine.get(reminder)['status'] == 'snoozed'
    assert engine.due_items() == []
    clock.set(datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc))
    assert [row['id'] for row in engine.due_items()] == [reminder]
    assert engine.reschedule(reminder, '2026-09-16T09:00:00+00:00')
    assert engine.get(reminder)['status'] == 'scheduled'
    assert engine.complete(reminder)
    assert engine.get(reminder)['status'] == 'completed'
    assert not engine.snooze(reminder, '2026-09-17T09:00:00+00:00')

    cancelled = engine.add('followup', 'Cancel me', due_at='2026-09-16T09:00:00+00:00')
    dismissed = engine.add('reminder', 'Dismiss me', due_at='2026-09-16T09:00:00+00:00')
    assert engine.cancel(cancelled)
    assert engine.dismiss(dismissed)
    assert engine.get(cancelled)['status'] == 'cancelled'
    assert engine.get(dismissed)['status'] == 'dismissed'


def test_date_only_due_uses_item_timezone_without_flaky_wall_clock(tmp_path):
    clock = Clock(datetime(2026, 9, 14, 22, 5, tzinfo=timezone.utc))
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', clock=clock, timezone_name='Europe/Berlin')
    item_id = engine.add('reminder', 'Date-only reminder', due_at='2026-09-15', timezone_name='Europe/Berlin')
    due = engine.due_items()
    assert [row['id'] for row in due] == [item_id]
    assert due[0]['overdue'] is False

    clock.set(datetime(2026, 9, 15, 22, 5, tzinfo=timezone.utc))
    due = engine.due_items(include_surfaced=True)
    assert due[0]['overdue'] is True


def test_followup_context_uses_only_existing_authorized_memories(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    brain = SecondBrain(store)
    normal_id = brain.remember(MemoryCandidate(
        type='person', subject='John', content='John owns the proposal review.', confidence=.9, source='explicit-user'
    ))
    secret_id = brain.remember(MemoryCandidate(
        type='decision', subject='Secret budget', content='Confidential budget decision.', confidence=.9,
        source='explicit-user', sensitivity='secret'
    ))
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', memory=store, second_brain=brain)
    item_id = engine.add(
        'followup',
        'Follow up with John about proposal',
        due_at='2026-09-15T00:00:00+00:00',
        related_memory_ids=[normal_id, secret_id, 'missing-memory'],
        evidence=[{'kind': 'conversation', 'id': 'conv-1'}],
    )

    default = engine.context_for_item(item_id)
    elevated = engine.context_for_item(item_id, allowed_sensitivities={'normal', 'secret'})
    assert [row['id'] for row in default] == [normal_id]
    assert {row['id'] for row in elevated} == {normal_id, secret_id}
    assert 'missing-memory' not in engine.get(item_id)['related_memory_ids']


def test_forgotten_is_evidence_based_excludes_future_terminal_and_superseded_and_deduplicates(tmp_path):
    clock = Clock(datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc))
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', clock=clock)
    unresolved = engine.add('commitment', 'Send the document', priority=.8)
    duplicate = engine.add('commitment', '  Send   the document ', priority=.7)
    overdue = engine.add('followup', 'Follow up with John', due_at='2026-09-15T10:00:00+00:00')
    future = engine.add('followup', 'Follow up next week', due_at='2026-09-22T10:00:00+00:00')
    completed = engine.add('commitment', 'Completed promise')
    cancelled = engine.add('commitment', 'Cancelled promise')
    old = engine.add('commitment', 'Old replaced promise')
    replacement = engine.add('commitment', 'Replacement promise', due_at='2026-09-20T10:00:00+00:00')
    engine.complete(completed)
    engine.cancel(cancelled)
    engine.supersede(old, replacement)

    forgotten = engine.forgotten()
    titles = {' '.join(row['title'].lower().split()) for row in forgotten}
    assert titles == {'send the document', 'follow up with john'}
    assert unresolved in {row['id'] for row in forgotten}
    assert overdue in {row['id'] for row in forgotten}
    assert duplicate not in {row['id'] for row in forgotten}
    assert future not in {row['id'] for row in forgotten}
    assert completed not in {row['id'] for row in forgotten}
    assert cancelled not in {row['id'] for row in forgotten}
    assert old not in {row['id'] for row in forgotten}


def test_daily_briefing_includes_today_overdue_high_priority_and_normal_memory_only(tmp_path):
    clock = Clock(datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc))
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    brain = SecondBrain(store)
    normal_id = brain.remember(MemoryCandidate(
        type='project', subject='Apollo', content='Apollo proposal is the current focus.', confidence=.9, source='explicit-user'
    ))
    secret_id = brain.remember(MemoryCandidate(
        type='project', subject='Apollo secret', content='Apollo confidential acquisition detail.', confidence=.9,
        source='explicit-user', sensitivity='secret'
    ))
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', memory=store, second_brain=brain, clock=clock)
    today = engine.add('commitment', 'Today commitment', due_at='2026-09-15', priority=.9)
    overdue = engine.add('followup', 'Overdue followup', due_at='2026-09-14', priority=.8)
    engine.add('goal', 'High priority goal', priority=.95)

    briefing = engine.briefing()
    assert today in {row['id'] for row in briefing['todays_commitments']}
    assert overdue in {row['id'] for row in briefing['overdue_followups']}
    assert normal_id in {row['id'] for row in briefing['relevant_memory']}
    assert secret_id not in {row['id'] for row in briefing['relevant_memory']}
    assert briefing['counts']['today'] == 1
    assert briefing['counts']['overdue'] == 1


def test_deleted_related_memory_is_not_retained_in_reminder_context_or_briefing(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    brain = SecondBrain(store)
    memory_id = brain.remember(MemoryCandidate(
        type='project', subject='Temporary', content='Temporary project context.', confidence=.9, source='explicit-user'
    ))
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', memory=store, second_brain=brain)
    item_id = engine.add('commitment', 'Commitment with memory', related_memory_ids=[memory_id])
    assert engine.context_for_item(item_id)
    brain.delete(memory_id)
    assert engine.context_for_item(item_id) == []
    assert memory_id not in {row['id'] for row in engine.briefing()['relevant_memory']}


def test_operational_audit_does_not_log_private_reminder_text(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', memory=store)
    private_text = 'Private reminder text that must not enter operational audit payloads'
    item_id = engine.add('reminder', private_text, due_at='2020-01-01T00:00:00+00:00')
    engine.refresh_due()
    engine.surface_due()
    engine.complete(item_id)

    local_audit = json.dumps(engine.history(item_id))
    global_audit = json.dumps(store.audit_entries('everyday', 100))
    assert private_text not in local_audit
    assert private_text not in global_audit


def test_owner_everyday_api_requires_trust_and_filters_sensitive_related_context(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    brain = SecondBrain(store)
    normal_id = brain.remember(MemoryCandidate(type='person', subject='John', content='John is the contact.', confidence=.9))
    secret_id = brain.remember(MemoryCandidate(type='fact', subject='Secret', content='Secret owner detail.', confidence=.9, sensitivity='secret'))
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', memory=store, second_brain=brain)
    item_id = engine.add('followup', 'Follow up', related_memory_ids=[normal_id, secret_id])

    app = FastAPI()
    app.include_router(everyday_intelligence_router({'device_registry': Registry(), 'everyday_intelligence': engine}))
    client = TestClient(app)
    assert client.get('/iphone/api/everyday/active').status_code == 401
    client.cookies.set('pa_device', 'dev-1')
    client.cookies.set('pa_token', 'token-1')
    assert client.get('/iphone/api/everyday/active').status_code == 200
    context = client.get(f'/iphone/api/everyday/{item_id}/context')
    assert context.status_code == 200
    payload = json.dumps(context.json())
    assert normal_id in payload
    assert secret_id not in payload
    assert 'Secret owner detail' not in payload


def test_reminder_evaluation_stays_bounded_with_five_thousand_future_items(tmp_path):
    clock = Clock(datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc))
    engine = EverydayIntelligence(tmp_path / 'everyday.sqlite3', clock=clock)
    stamp = clock().isoformat()
    rows = [
        (
            f'perf-{index}', 'reminder', f'Reminder {index}', 'scheduled', .5,
            '2027-09-15T12:00:00+00:00', '', 'qualification-fixture', stamp, stamp,
            'UTC', None, None, None, None, None, None, '[]', '[]', 0, None,
        )
        for index in range(5000)
    ]
    with engine._con() as con:
        con.executemany(
            '''INSERT INTO everyday_items(
                id,kind,title,status,priority,due_at,context,source,created_at,updated_at,timezone,
                snoozed_until,surfaced_at,completed_at,dismissed_at,cancelled_at,superseded_by,
                related_memory_ids_json,evidence_json,surface_count,last_surface_key)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            rows,
        )
    started = time.perf_counter()
    assert engine.due_items() == []
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0
