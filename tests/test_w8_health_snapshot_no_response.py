from pathlib import Path

def test_observability_module_has_no_model_response_store():assert "'response'" not in Path('models/resilience.py').read_text(encoding='utf-8').lower()
