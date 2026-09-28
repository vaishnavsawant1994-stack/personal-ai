from pathlib import Path

def test_w8_implementation_contains_no_live_provider_verification_claim():
    combined=Path('models/resilience.py').read_text(encoding='utf-8')+Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'LIVE PROVIDER VERIFIED' not in combined and 'PRODUCTION VERIFIED' not in combined
