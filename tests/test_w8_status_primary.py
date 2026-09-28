from pathlib import Path

def test_w8_status_preserves_primary_provider_field():assert "'primary_provider': self.primary" in Path('models/router.py').read_text(encoding='utf-8')
