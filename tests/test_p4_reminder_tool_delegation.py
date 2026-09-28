from __future__ import annotations

from future_intelligence.everyday import EverydayIntelligence
from memory.store import MemoryStore
from tools import reminders


class Registry:
    def __init__(self):
        self.tools = {}

    def register(self, tool):
        self.tools[tool.name] = tool


def test_create_reminder_delegates_to_authoritative_everyday_lifecycle(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    everyday = EverydayIntelligence(tmp_path / 'everyday.sqlite3', memory=store)
    store.everyday_intelligence = everyday
    registry = Registry()
    reminders.register(registry, store)

    result = registry.tools['create_reminder'].handler({
        'title': 'Send proposal',
        'due_at': '2026-09-16T09:00:00+00:00',
        'priority': .9,
    })

    assert result['ok'] is True
    assert result['authority'] == 'everyday_intelligence'
    item = everyday.get(result['task_id'])
    assert item['title'] == 'Send proposal'
    assert item['status'] == 'scheduled'
    with store.con() as con:
        assert con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0


def test_reminder_transition_tools_share_the_same_lifecycle_record(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    everyday = EverydayIntelligence(tmp_path / 'everyday.sqlite3', memory=store)
    store.everyday_intelligence = everyday
    registry = Registry()
    reminders.register(registry, store)

    created = registry.tools['create_reminder'].handler({'title': 'Call John'})
    item_id = created['task_id']
    assert registry.tools['snooze_reminder'].handler({
        'task_id': item_id,
        'until': '2026-09-16T10:00:00+00:00',
    })['ok'] is True
    assert everyday.get(item_id)['status'] == 'snoozed'
    assert registry.tools['complete_reminder'].handler({'task_id': item_id})['ok'] is True
    assert everyday.get(item_id)['status'] == 'completed'
