from pathlib import Path

def test_w8_observability_is_bounded_memory_not_new_database_authority():
    text=Path('models/resilience.py').read_text(encoding='utf-8').lower()
    assert 'sqlite' not in text and 'postgres' not in text
