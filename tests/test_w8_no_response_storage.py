from pathlib import Path

def test_generation_observability_is_metadata_only():
    allow=Path('models/resilience.py').read_text(encoding='utf-8').split('SAFE_FIELDS =',1)[1].split('}',1)[0];assert 'result' in allow and 'latency_ms' in allow and 'response' not in allow
