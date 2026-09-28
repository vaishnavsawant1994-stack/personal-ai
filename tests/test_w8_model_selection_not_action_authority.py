from pathlib import Path

def test_model_selection_remains_separate_from_action_authorization():
    text=Path('models/governed_router.py').read_text(encoding='utf-8').lower()
    assert 'approval_ticket' not in text and 'policy_gateway' not in text and 'operator_transactions' not in text
