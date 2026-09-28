from pathlib import Path

def test_owner_diagnostics_include_recent_generations_but_not_content():
    text=Path('models/resilience.py').read_text(encoding='utf-8');assert "'recent_generations':" in text
