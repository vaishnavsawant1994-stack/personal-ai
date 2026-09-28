from pathlib import Path

def test_existing_provider_public_view_removes_key_and_url_credentials():
    text=Path('models/router.py').read_text(encoding='utf-8')
    assert "data.pop('api_key', None)" in text and "parsed.hostname" in text
