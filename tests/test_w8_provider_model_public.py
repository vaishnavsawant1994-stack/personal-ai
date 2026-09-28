from pathlib import Path

def test_existing_provider_public_view_keeps_model_and_capabilities():
    text=Path('models/router.py').read_text(encoding='utf-8');assert 'asdict(self)' in text and "data.pop('api_key', None)" in text
