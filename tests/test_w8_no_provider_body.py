from pathlib import Path

def test_w8_governance_does_not_parse_or_store_provider_error_bodies():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert '.response.text' not in text and '.content.decode' not in text
