from pathlib import Path

def test_model_retry_layer_has_no_tool_or_operator_retry_logic():
    text=Path('models/governed_router.py').read_text(encoding='utf-8').lower()
    assert 'tool retry' not in text and 'operator retry' not in text and 'compensation' not in text
