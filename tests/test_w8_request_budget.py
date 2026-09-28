from pathlib import Path

def test_failover_budget_is_enforced_by_candidate_slice():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'candidates[:self.max_failovers+1]' in text
