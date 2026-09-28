from __future__ import annotations

from datetime import datetime, timedelta, timezone

from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore


def brain(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    return SecondBrain(store), store


def test_retrieval_explanation_is_attached_only_to_real_selected_memories(tmp_path):
    second_brain, store = brain(tmp_path)
    memory_id = second_brain.remember(
        MemoryCandidate(
            type='preference',
            subject='Coffee',
            content='Owner prefers a flat white in the morning.',
            confidence=.96,
            source='explicit-user',
            verified=True,
            evidence=[{'kind': 'message', 'id': 'm-1'}],
        )
    )
    related_id = second_brain.remember(
        MemoryCandidate(
            type='fact',
            subject='Cafe',
            content='The nearby cafe serves flat white coffee.',
            confidence=.8,
            source='explicit-user',
        )
    )
    store.relate(memory_id, 'related_to', related_id)

    rows = second_brain.context('flat white', 10)
    selected = next(row for row in rows if row['id'] == memory_id)
    explanation = selected['retrieval_explanation']

    assert explanation['retrieved'] is True
    assert explanation['memory_id'] == memory_id
    assert explanation['subject'] == 'Coffee'
    assert explanation['source'] == 'explicit-user'
    assert explanation['verified'] is True
    assert explanation['retrieval_query'] == 'flat white'
    assert explanation['used_at']
    assert explanation['relationship_count'] == 1
    assert explanation['relationship_contribution'] == 0.0
    assert explanation['evidence_references'] == [{'kind': 'message', 'id': 'm-1'}]
    assert explanation['selection_reason']
    assert second_brain.explain_retrieval(memory_id, 'not-present-anywhere') is None


def test_old_historical_and_conflicting_memories_explain_state(tmp_path):
    second_brain, _ = brain(tmp_path)
    old_time = (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()
    old_id = second_brain.remember(
        MemoryCandidate(
            type='preference',
            subject='Travel seat',
            content='Owner prefers aisle seats for flights.',
            confidence=.8,
            source='explicit-user',
            occurred_at=old_time,
        )
    )
    new_id = second_brain.remember(
        MemoryCandidate(
            type='preference',
            subject='Travel seat',
            content='Owner now prefers window seats for flights.',
            confidence=.95,
            source='explicit-user',
        )
    )

    rows = second_brain.context('flights', 20)
    by_id = {row['id']: row for row in rows}
    assert by_id[old_id]['retrieval_explanation']['memory_state'] == 'historical'
    assert by_id[old_id]['retrieval_explanation']['contradiction_state'] == 'superseded'
    assert by_id[old_id]['retrieval_explanation']['age_days'] > 700
    assert by_id[new_id]['retrieval_explanation']['memory_state'] == 'active'


def test_sensitive_and_never_store_memories_are_not_selected_when_disallowed(tmp_path):
    second_brain, store = brain(tmp_path)
    normal_id = second_brain.remember(
        MemoryCandidate(type='fact', subject='Project', content='Project codename is Atlas.', confidence=.9)
    )
    secret_id = second_brain.remember(
        MemoryCandidate(
            type='fact',
            subject='Secret project',
            content='Secret project codename is Atlas Black.',
            confidence=.9,
            sensitivity='secret',
        )
    )
    stamp = datetime.now(timezone.utc).isoformat()
    with store.con() as con:
        con.execute(
            '''INSERT INTO memories(
                id,type,subject,content,source,confidence,verified,sensitivity,parent_id,tags_json,
                created_at,updated_at,importance,occurred_at,last_used_at,use_count,valid_from,valid_to,
                superseded_by,evidence_json,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,'[]','{}')''',
            (
                'legacy-never-store', 'fact', 'Legacy', 'Atlas should never be stored',
                'legacy', 1.0, 0, 'never_store', None, '[]',
                stamp, stamp, .5, None, None, 0, stamp,
            ),
        )

    rows = second_brain.context('Atlas', 20, allowed_sensitivities={'normal'})
    ids = {row['id'] for row in rows}
    assert normal_id in ids
    assert secret_id not in ids
    assert 'legacy-never-store' not in ids


def test_deleted_memory_cannot_receive_retrieval_explanation(tmp_path):
    second_brain, _ = brain(tmp_path)
    memory_id = second_brain.remember(
        MemoryCandidate(type='fact', subject='Delete me', content='Temporary unique retrieval token.', confidence=.9)
    )
    assert second_brain.delete(memory_id) is True
    assert second_brain.explain_retrieval(memory_id, 'unique retrieval token') is None
