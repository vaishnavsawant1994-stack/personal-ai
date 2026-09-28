from pathlib import Path

def test_w8_changed_runtime_has_no_railway_client_import():
    combined=Path('app/main.py').read_text(encoding='utf-8')+Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'import railway' not in combined.lower()
