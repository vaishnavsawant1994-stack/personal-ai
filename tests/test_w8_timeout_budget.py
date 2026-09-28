from pathlib import Path

def test_model_calls_keep_existing_request_timeout_and_separate_health_timeout():
    base=Path('models/router.py').read_text(encoding='utf-8');w8=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'model_request_timeout_seconds' in base and 'self.health_timeout' in w8
