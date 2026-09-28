from pathlib import Path

def test_health_probe_uses_dedicated_bounded_timeout():
    text=Path('models/governed_router.py').read_text(encoding='utf-8').split('def health_status',1)[1]
    assert 'timeout=self.health_timeout' in text
