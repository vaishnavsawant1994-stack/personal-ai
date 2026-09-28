from pathlib import Path


def test_model_failover_does_not_authorize_side_effects():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    for forbidden in ('execute_tool(', 'dispatch_action(', 'issue_approval(', 'create_transaction('):
        assert forbidden not in text


def test_emergency_stop_authority_is_not_reimplemented_in_model_router():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'emergency_stop' not in text.lower()
    assert 'TrustedAction' not in text
