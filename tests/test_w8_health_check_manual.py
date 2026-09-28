from pathlib import Path

def test_owner_health_check_is_explicit_button_action():
    text=Path('ui/settings_panel.py').read_text(encoding='utf-8');assert "mprobe.clicked.connect(lambda:self.refresh_model_view(True))" in text
