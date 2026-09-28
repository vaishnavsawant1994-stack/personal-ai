from pathlib import Path

def test_owner_model_view_uses_router_public_status_only():
    text=Path('ui/settings_panel.py').read_text(encoding='utf-8');assert 'models.health_status' in text and 'models.providers' not in text
