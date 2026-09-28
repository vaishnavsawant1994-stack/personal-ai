from pathlib import Path


def test_existing_sensitive_external_restriction_remains_in_base_router():
    text=Path('models/router.py').read_text(encoding='utf-8')
    assert "sensitivity in {'sensitive', 'secret'}" in text
    assert 'not self.allow_external_sensitive' in text
