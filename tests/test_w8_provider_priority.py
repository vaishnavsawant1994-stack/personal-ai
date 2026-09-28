from pathlib import Path

def test_w8_reuses_existing_candidate_priority_and_local_first_policy():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'self._candidates(capability, sensitivity)' in text
