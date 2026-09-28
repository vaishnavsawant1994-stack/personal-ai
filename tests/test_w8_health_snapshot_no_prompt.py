from pathlib import Path

def test_observability_module_has_no_prompt_store():assert 'prompt' not in Path('models/resilience.py').read_text(encoding='utf-8').lower()
