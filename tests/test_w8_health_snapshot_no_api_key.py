from pathlib import Path

def test_observability_module_has_no_api_key_field():assert 'api_key' not in Path('models/resilience.py').read_text(encoding='utf-8')
