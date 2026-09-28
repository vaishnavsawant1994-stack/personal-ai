from pathlib import Path

def test_governed_router_does_not_persist_provider_exception_text():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'str(exc)' not in text
    assert 'repr(exc)' not in text
