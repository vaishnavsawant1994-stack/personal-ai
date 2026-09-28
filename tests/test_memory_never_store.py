from __future__ import annotations

import pytest

from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore


class ExtractionModel:
    def json(self, *_args, **_kwargs):
        return {
            'memories': [
                {
                    'type': 'fact',
                    'subject': 'temporary secret',
                    'content': 'do not retain this',
                    'confidence': 1,
                    'sensitivity': 'never_store',
                },
                {
                    'type': 'preference',
                    'subject': 'theme',
                    'content': 'prefers dark mode',
                    'confidence': .9,
                    'sensitivity': 'normal',
                },
            ]
        }


def test_never_store_is_rejected_at_all_write_boundaries(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    brain = SecondBrain(store)

    with pytest.raises(ValueError, match='NEVER_STORE'):
        store.remember(
            type='fact', subject='secret', content='temporary', sensitivity='never_store'
        )
    with pytest.raises(ValueError, match='NEVER_STORE'):
        brain.remember(
            MemoryCandidate('fact', 'secret', 'temporary', 1, sensitivity='NEVER-STORE')
        )

    memory_id = store.remember(type='fact', subject='safe', content='stored')
    with pytest.raises(ValueError, match='NEVER_STORE'):
        store.update_memory(memory_id, sensitivity='never store')
    assert store.get(memory_id)['content'] == 'stored'


def test_never_store_candidates_are_discarded_during_extraction(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    candidates = SecondBrain(store, models=ExtractionModel()).extract_candidates(
        'Remember dark mode, but do not retain the temporary secret.'
    )

    assert [(item.subject, item.sensitivity) for item in candidates] == [('theme', 'normal')]


def test_legacy_never_store_rows_are_suppressed_from_every_retrieval_path(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    safe_id = store.remember(type='fact', subject='visible', content='allowed')
    hidden_id = 'legacy-never-store'
    with store.con() as con:
        con.execute(
            '''INSERT INTO memories(
                id,type,subject,content,source,confidence,verified,sensitivity,parent_id,tags_json,
                created_at,updated_at,importance,occurred_at,last_used_at,use_count,valid_from,valid_to,
                superseded_by,evidence_json,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,'[]','{}')''',
            (
                hidden_id, 'fact', 'hidden', 'must not surface', 'legacy', 1, 1,
                'never-store', None, '[]', '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00', .5, None, None, 0,
                '2026-01-01T00:00:00+00:00',
            ),
        )
        con.execute(
            'INSERT INTO relations(id,source_id,relation,target_id,created_at) VALUES(?,?,?,?,?)',
            ('hidden-edge', safe_id, 'related_to', hidden_id, '2026-01-01T00:00:00+00:00'),
        )

    assert store.get(hidden_id) is None
    assert store.search('must not surface') == []
    assert store.active_subject('fact', 'hidden') == []
    assert store.temporal_search('hidden') == []
    assert store.record_usage(hidden_id, query='hidden') is None
    assert store.usage(hidden_id) == []
    assert store.conflicts() == []
    assert {row['id'] for row in store.graph()['nodes']} == {safe_id}
    assert store.graph()['edges'] == []
    assert {row['id'] for row in store.export()['memories']} == {safe_id}
    assert [row['id'] for row in store.tree()] == [safe_id]
