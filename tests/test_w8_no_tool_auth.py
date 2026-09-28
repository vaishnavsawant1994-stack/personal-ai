from pathlib import Path

def test_w8_model_router_does_not_issue_tool_permissions():
    text=Path('models/governed_router.py').read_text(encoding='utf-8').lower();assert 'permission' not in text and 'approval' not in text
