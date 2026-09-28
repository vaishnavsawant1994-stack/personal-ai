from pathlib import Path

def test_w8_router_never_records_settings_object_or_environment():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert "_record('model" in text
    assert 'self.settings)' not in text
    assert 'os.environ' not in text
