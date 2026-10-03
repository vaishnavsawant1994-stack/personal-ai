from datetime import datetime, timedelta, timezone

from memory.governance import GovernedMemory
from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore


def build(tmp_path):
    store = MemoryStore(tmp_path / 'memories.sqlite3')
    brain = SecondBrain(store)
    return store, GovernedMemory(brain, tmp_path / 'governance.sqlite3')


def test_ambient_preferences_persist_and_gate_conversation_candidates(tmp_path):
    _, governed = build(tmp_path)
    candidate = MemoryCandidate('preference', 'Theme', 'Prefers dark theme', .8, source='user-message')
    assert governed.ambient_settings()['enabled'] is False
    assert governed.remember(candidate) is None
    governed.update_ambient_settings({'enabled': True})
    candidate_id = governed.remember(candidate)
    assert candidate_id
    restarted = GovernedMemory(SecondBrain(MemoryStore(tmp_path / 'memories.sqlite3')), tmp_path / 'governance.sqlite3')
    assert restarted.ambient_settings()['enabled'] is True
    restarted.update_ambient_settings({'enabled': True})
    restarted.update_ambient_settings({'sources': {'conversations': False}})
    assert restarted.ambient_settings()['enabled'] is False
    assert restarted.remember(candidate) is None
    # Explicit owner writes do not depend on Ambient being enabled.
    explicit = MemoryCandidate('note', 'Owner note', 'Keep this note', 1, source='explicit-owner', verified=True)
    assert restarted.remember(explicit)


def test_ambient_cleanup_only_selects_stale_unused_low_value_unlinked_normal_memories(tmp_path):
    store, governed = build(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    def save(subject, *, importance=.2, sensitivity='normal'):
        mid = store.remember(type='note', subject=subject, content=subject, source='owner-confirmed:user-message', confidence=.7, verified=True, sensitivity=sensitivity, importance=importance)
        with store.con() as con:
            con.execute('UPDATE memories SET created_at=?,updated_at=?,occurred_at=? WHERE id=?', (old, old, old, mid))
        return mid
    eligible = save('stale low value')
    important = save('important', importance=.8)
    sensitive = save('sensitive', sensitivity='sensitive')
    used = save('used')
    store.record_usage(used, query='recent context')
    related = save('related')
    other = store.remember(type='note', subject='other', content='other', source='explicit-owner', verified=True)
    store.relate(related, 'related_to', other)

    governed.update_ambient_settings({'auto_clean': True, 'retention_days': 365})
    result = governed.run_ambient_auto_clean(older_than_days=governed.ambient_settings()['retention_days'])
    assert result['deleted'] == 1
    assert store.get(eligible) is None
    assert store.get(important) is not None
    assert store.get(sensitive) is not None
    assert store.get(used) is not None
    assert store.get(related) is not None
