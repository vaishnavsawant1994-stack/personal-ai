from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time

import pytest

from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore
from memory.vector_store import VectorStore


def brain(tmp_path, *, vector=False):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    if not vector:
        return SecondBrain(store), store

    def embed(text):
        value = str(text).lower()
        return [
            1.0 if 'apollo' in value else 0.0,
            1.0 if 'budget' in value else 0.0,
            1.0 if 'john' in value else 0.0,
        ]

    vectors = VectorStore(tmp_path / 'vectors.sqlite3', embed)
    return SecondBrain(store, vector_store=vectors), store


def bulk_insert(store, count, *, marker_index=None):
    stamp = datetime.now(timezone.utc).isoformat()
    rows = []
    for index in range(count):
        memory_id = f'bulk-{count}-{index}'
        marker = f' needle-{count}-{index}' if marker_index == index else ''
        rows.append((
            memory_id,
            'fact',
            f'Bulk subject {index}',
            f'Deterministic corpus row {index}.{marker}',
            'qualification-fixture',
            .8,
            1,
            'normal',
            None,
            '[]',
            stamp,
            stamp,
            .5,
            stamp,
            None,
            0,
            stamp,
            None,
            None,
            '[]',
            '{}',
        ))
    with store.con() as con:
        con.executemany(
            '''INSERT INTO memories(
                id,type,subject,content,source,confidence,verified,sensitivity,parent_id,tags_json,
                created_at,updated_at,importance,occurred_at,last_used_at,use_count,valid_from,valid_to,
                superseded_by,evidence_json,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            rows,
        )


@pytest.mark.parametrize('count', [100, 1000, 5000])
def test_large_corpus_retrieval_is_correct_and_bounded(tmp_path, count):
    second_brain, store = brain(tmp_path)
    target_index = count - 1
    bulk_insert(store, count, marker_index=target_index)

    started = time.perf_counter()
    rows = second_brain.context(f'needle-{count}-{target_index}', limit=5, current_only=True)
    elapsed = time.perf_counter() - started

    assert rows
    assert rows[0]['id'] == f'bulk-{count}-{target_index}'
    assert all(row['truth_state'] == 'CURRENT' for row in rows)
    assert elapsed < 5.0


def test_semantic_retrieval_uses_existing_vector_store_and_explains_actual_factor(tmp_path):
    second_brain, _ = brain(tmp_path, vector=True)
    apollo = second_brain.remember(MemoryCandidate(
        type='project', subject='Apollo', content='Apollo launch readiness review.', confidence=.9, source='explicit-user'
    ))
    second_brain.remember(MemoryCandidate(
        type='project', subject='Orion', content='Orion design review.', confidence=.9, source='explicit-user'
    ))

    row = second_brain.context('Apollo', limit=1, current_only=True)[0]
    explanation = row['retrieval_explanation']
    assert row['id'] == apollo
    assert explanation['semantic_score'] == pytest.approx(1.0)
    assert explanation['retrieval_mode'] == 'semantic'
    assert explanation['relevance_score'] == row['salience_score']
    assert explanation['importance_contribution'] > 0
    assert explanation['recency_contribution'] > 0


def test_relationship_expansion_adds_real_graph_context_and_real_contribution(tmp_path):
    second_brain, store = brain(tmp_path)
    person = second_brain.remember(MemoryCandidate(
        type='person', subject='John', content='John leads the client relationship.', confidence=.9, source='explicit-user'
    ))
    project = second_brain.remember(MemoryCandidate(
        type='project', subject='Apollo', content='Apollo is the proposal project.', confidence=.9, source='explicit-user'
    ))
    store.relate(person, 'involves', project)

    rows = second_brain.context('John', limit=5, current_only=True)
    by_id = {row['id']: row for row in rows}
    assert person in by_id
    assert project in by_id
    explanation = by_id[project]['retrieval_explanation']
    assert explanation['retrieval_mode'] == 'relationship'
    assert explanation['relationship_contribution'] > 0
    assert explanation['relationship_count'] == 1


def test_hidden_relationship_does_not_create_sensitive_metadata_side_channel(tmp_path):
    second_brain, store = brain(tmp_path)
    normal_id = second_brain.remember(MemoryCandidate(
        type='person', subject='John', content='John is a public project contact.', confidence=.9, source='explicit-user'
    ))
    secret_id = second_brain.remember(MemoryCandidate(
        type='project', subject='Secret Apollo', content='Secret acquisition budget.', confidence=.9, source='explicit-user', sensitivity='secret'
    ))
    store.relate(normal_id, 'related_to', secret_id)

    rows = second_brain.context('John', limit=5, current_only=True)
    assert [row['id'] for row in rows] == [normal_id]
    explanation = rows[0]['retrieval_explanation']
    assert explanation['relationship_count'] == 0
    assert explanation['relationship_contribution'] == 0
    assert 'Secret Apollo' not in json.dumps(rows)


def test_default_context_is_fail_closed_to_normal_memory(tmp_path):
    second_brain, _ = brain(tmp_path)
    normal_id = second_brain.remember(MemoryCandidate(
        type='fact', subject='Atlas', content='Atlas public schedule.', confidence=.9, sensitivity='normal'
    ))
    secret_id = second_brain.remember(MemoryCandidate(
        type='fact', subject='Atlas secret', content='Atlas confidential budget.', confidence=.9, sensitivity='secret'
    ))

    default_ids = {row['id'] for row in second_brain.context('Atlas', limit=10)}
    elevated_ids = {row['id'] for row in second_brain.context('Atlas', limit=10, allowed_sensitivities={'normal', 'secret'})}
    assert default_ids == {normal_id}
    assert {normal_id, secret_id}.issubset(elevated_ids)


def test_multistep_supersession_resolves_current_truth_and_delete_does_not_resurrect(tmp_path):
    second_brain, _ = brain(tmp_path)
    a = second_brain.remember(MemoryCandidate(type='status', subject='Meeting', content='Meeting is at 10:00.', confidence=.9, source='explicit-user'))
    b = second_brain.remember(MemoryCandidate(type='status', subject='Meeting', content='Meeting moved to 11:00.', confidence=.9, source='explicit-user'))
    c = second_brain.remember(MemoryCandidate(type='status', subject='Meeting', content='Meeting moved to 11:30.', confidence=.9, source='explicit-user'))

    current = second_brain.current_truth('Meeting', limit=10)
    assert [row['id'] for row in current] == [c]
    historical = {row['id']: row for row in second_brain.temporal('Meeting', limit=10)}
    assert historical[a]['memory_state'] == 'historical'
    assert historical[a]['contradiction_state'] == 'superseded'
    assert historical[b]['memory_state'] == 'historical'
    assert historical[c]['truth_state'] == 'CURRENT'

    assert second_brain.delete(c) is True
    assert second_brain.current_truth('Meeting', limit=10) == []
    remaining = {row['id'] for row in second_brain.temporal('Meeting', limit=10)}
    assert remaining == {a, b}


def test_context_at_returns_state_that_was_valid_at_that_time(tmp_path):
    second_brain, store = brain(tmp_path)
    a = store.remember(
        type='decision', subject='Hosting', content='Use provider A.', source='explicit-user', confidence=.9,
        occurred_at='2026-01-01T09:00:00+00:00', valid_from='2026-01-01T09:00:00+00:00'
    )
    b = store.remember(
        type='decision', subject='Hosting', content='Use provider B.', source='explicit-user', confidence=.9,
        occurred_at='2026-02-01T09:00:00+00:00', valid_from='2026-02-01T09:00:00+00:00'
    )
    store.update_memory(a, valid_to='2026-02-01T09:00:00+00:00', superseded_by=b)

    january = second_brain.context_at('Hosting', '2026-01-15T12:00:00+00:00', memory_type='decision')
    march = second_brain.context_at('Hosting', '2026-03-01T12:00:00+00:00', memory_type='decision')
    assert [row['id'] for row in january] == [a]
    assert [row['id'] for row in march] == [b]
    assert january[0]['memory_state'] == 'current_at_time'


def test_exact_duplicate_is_deduplicated(tmp_path):
    second_brain, _ = brain(tmp_path)
    candidate = MemoryCandidate(type='project', subject='Apollo', content='Apollo is active.', confidence=.8, source='explicit-user')
    first = second_brain.remember(candidate)
    second = second_brain.remember(candidate)
    assert first == second
    assert len(second_brain.graph()['nodes']) == 1


def test_retention_and_deletion_remove_memory_from_all_authoritative_retrieval(tmp_path):
    second_brain, _ = brain(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()
    memory_id = second_brain.remember(MemoryCandidate(
        type='event', subject='Old event', content='Ancient qualification note.', confidence=.8, occurred_at=old
    ))
    result = second_brain.apply_retention(older_than_days=365, dry_run=False)
    assert memory_id in result['memory_ids']
    assert second_brain.context('Ancient qualification', limit=10) == []
    assert second_brain.temporal('Ancient qualification', limit=10) == []
    assert memory_id not in {row['id'] for row in second_brain.graph()['nodes']}


def test_context_character_budget_is_bounded_without_mutating_memory(tmp_path):
    second_brain, _ = brain(tmp_path)
    ids = []
    for index in range(8):
        ids.append(second_brain.remember(MemoryCandidate(
            type='note', subject=f'Budget {index}', content=('context-block-' + str(index) + ' ') * 20,
            confidence=.9, source='explicit-user'
        )))
    rows = second_brain.context('', limit=8, current_only=True, max_context_chars=700)
    used = sum(len(str(row.get('subject') or '')) + len(str(row.get('content') or '')) for row in rows)
    assert 1 <= len(rows) < len(ids)
    assert used <= 700
