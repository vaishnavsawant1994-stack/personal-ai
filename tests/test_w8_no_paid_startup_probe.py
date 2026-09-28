from pathlib import Path

def test_runtime_construction_does_not_trigger_health_probe():
    text=Path('app/main.py').read_text(encoding='utf-8');assert 'health_status(probe=True)' not in text and 'status(probe=True)' not in text
