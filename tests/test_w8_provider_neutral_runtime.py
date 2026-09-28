from pathlib import Path

def test_runtime_imports_governance_not_specific_provider_sdk():
    text=Path('app/main.py').read_text(encoding='utf-8');assert 'models.governed_router' in text and 'openai import' not in text.lower() and 'google.generativeai' not in text.lower()
