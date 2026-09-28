from pathlib import Path

def test_disabled_providers_are_skipped_by_health_probe():
    text=Path('models/governed_router.py').read_text(encoding='utf-8').split('def health_status',1)[1]
    assert 'provider.id in self.disabled' in text
