from pathlib import Path


def test_health_checks_are_explicit_not_background_polling():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'while True' not in text
    assert 'threading.Timer' not in text
    assert 'health_status(self, *, probe: bool = False)' in text
