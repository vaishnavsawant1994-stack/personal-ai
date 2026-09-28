from pathlib import Path

def test_router_has_no_unbounded_retry_loop():
    text=Path('models/governed_router.py').read_text(encoding='utf-8');assert 'while' not in text.split('def _run',1)[1].split('def health_status',1)[0]
