from pathlib import Path

def test_w8_status_preserves_fallback_provider_field():assert "'fallback_providers': list(self.fallbacks)" in Path('models/router.py').read_text(encoding='utf-8')
