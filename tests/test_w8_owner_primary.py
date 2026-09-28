from pathlib import Path

def test_owner_can_see_primary_and_fallbacks_in_existing_status_contract():
    text=Path('models/router.py').read_text(encoding='utf-8')
    assert "'primary_provider': self.primary" in text and "'fallback_providers': list(self.fallbacks)" in text
