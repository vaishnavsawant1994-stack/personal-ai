from pathlib import Path


def test_router_uses_bounded_loops_not_recursive_run_calls():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    body=text.split('def _run(',1)[1].split('\n    def ',1)[0]
    assert 'self._run(' not in body
    assert 'candidates[:self.max_failovers+1]' in body
