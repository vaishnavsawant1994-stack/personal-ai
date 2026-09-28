from pathlib import Path


def test_governance_layer_is_provider_neutral():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'api.openai.com' not in text
    assert 'generativelanguage.googleapis.com' not in text
    assert 'openrouter.ai' not in text
    assert 'requests.request' not in text
