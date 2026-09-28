from pathlib import Path

def test_observability_module_has_no_secret_value_store():
    text=Path('models/resilience.py').read_text(encoding='utf-8').lower();assert 'password' not in text and 'cookie' not in text and 'authorization' not in text
