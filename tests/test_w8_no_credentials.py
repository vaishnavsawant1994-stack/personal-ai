from pathlib import Path

def test_w8_source_contains_no_committed_bearer_credentials():
    combined='\n'.join(Path(p).read_text(encoding='utf-8') for p in ('models/resilience.py','models/governed_router.py'))
    assert 'sk-proj-' not in combined and 'Bearer ey' not in combined
