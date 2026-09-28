from pathlib import Path

def test_health_probe_uses_existing_provider_request_adapter():
    text=Path('models/governed_router.py').read_text(encoding='utf-8').split('def health_status',1)[1]
    assert 'self._request(provider' in text
