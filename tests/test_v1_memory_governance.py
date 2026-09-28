from __future__ import annotations

import pytest

from memory.governance import GovernedMemory
from memory.second_brain import MemoryCandidate


class Store:
    second_brain = None


class Brain:
    def __init__(self):
        self.store = Store()
        self.saved = []

    def remember(self, candidate):
        self.saved.append(candidate)
        return f'memory-{len(self.saved)}'

    def context(self, query, limit=8, **kwargs):
        return []


def candidate(**changes):
    data = dict(
        type='preference',
        subject='coffee',
        content='Owner prefers espresso',
        confidence=0.9,
        source='conversation',
        verified=False,
        sensitivity='normal',
    )
    data.update(changes)
    return MemoryCandidate(**data)


def test_unverified_model_candidate_is_quarantined_not_committed(tmp_path):
    raw = Brain()
    memory = GovernedMemory(raw, tmp_path / 'candidates.sqlite3')
    candidate_id = memory.remember(candidate())
    assert candidate_id
    assert raw.saved == []
    pending = memory.candidates()
    assert len(pending) == 1
    assert pending[0]['id'] == candidate_id
    assert pending[0]['candidate']['content'] == 'Owner prefers espresso'


def test_verified_explicit_owner_memory_commits_immediately(tmp_path):
    raw = Brain()
    memory = GovernedMemory(raw, tmp_path / 'candidates.sqlite3')
    memory_id = memory.remember(candidate(source='explicit-user', verified=True))
    assert memory_id == 'memory-1'
    assert len(raw.saved) == 1
    assert memory.candidates() == []


def test_unverified_sensitive_or_never_store_candidate_is_not_persisted(tmp_path):
    raw = Brain()
    memory = GovernedMemory(raw, tmp_path / 'candidates.sqlite3')
    assert memory.remember(candidate(sensitivity='sensitive')) is None
    assert memory.remember(candidate(sensitivity='never_store')) is None
    assert raw.saved == []
    assert memory.candidates() == []


def test_owner_can_confirm_candidate_and_confirmation_becomes_provenance(tmp_path):
    raw = Brain()
    memory = GovernedMemory(raw, tmp_path / 'candidates.sqlite3')
    candidate_id = memory.remember(candidate(source='conversation'))
    memory_id = memory.approve_candidate(candidate_id, owner_id='owner')
    assert memory_id == 'memory-1'
    assert len(raw.saved) == 1
    promoted = raw.saved[0]
    assert promoted.verified is True
    assert promoted.source == 'owner-confirmed:conversation'
    assert memory.candidates() == []


def test_non_owner_cannot_confirm_or_reject_candidate(tmp_path):
    raw = Brain()
    memory = GovernedMemory(raw, tmp_path / 'candidates.sqlite3')
    candidate_id = memory.remember(candidate())
    with pytest.raises(PermissionError, match='canonical owner'):
        memory.approve_candidate(candidate_id, owner_id='other')
    with pytest.raises(PermissionError, match='canonical owner'):
        memory.reject_candidate(candidate_id, owner_id='other')
    assert len(memory.candidates()) == 1
