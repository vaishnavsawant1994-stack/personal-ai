from pathlib import Path

def test_health_filter_is_applied_after_existing_privacy_capability_candidate_filter():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    eligible=text.split('def _eligible',1)[1].split('def _run',1)[0]
    assert 'self._candidates(capability, sensitivity)' in eligible
    assert 'self.observability.allowed(provider.id)' in eligible
