from pathlib import Path

def test_w8_health_layer_cannot_override_base_sensitive_candidate_filter():
    base=Path('models/router.py').read_text(encoding='utf-8');w8=Path('models/governed_router.py').read_text(encoding='utf-8');assert 'allow_external_sensitive' in base and 'self._candidates(capability, sensitivity)' in w8
