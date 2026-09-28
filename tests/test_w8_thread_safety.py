from pathlib import Path

def test_observability_uses_reentrant_lock_for_shared_health_state():
    text=Path('models/resilience.py').read_text(encoding='utf-8')
    assert 'threading.RLock()' in text
