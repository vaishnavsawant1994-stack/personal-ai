from pathlib import Path


def test_health_probe_uses_models_endpoint_not_generation_endpoint():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    health=text.split('def health_status',1)[1]
    assert "'GET','/models'" in health
    assert '/chat/completions' not in health
    assert 'prompt' not in health
