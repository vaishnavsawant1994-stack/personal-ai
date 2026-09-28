from pathlib import Path


def test_retry_and_failover_settings_are_bounded_in_router():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'min(3' in text
    assert 'min(len(self.providers) - 1' in text
