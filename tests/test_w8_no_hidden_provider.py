from pathlib import Path

def test_w8_does_not_add_new_provider_adapter():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'Provider(' not in text
