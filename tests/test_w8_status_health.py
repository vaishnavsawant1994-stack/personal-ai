from pathlib import Path

def test_owner_status_contains_circuit_and_provider_health():
    text=Path('models/resilience.py').read_text(encoding='utf-8')
    assert "'providers':" in text and "'circuit':" in text
