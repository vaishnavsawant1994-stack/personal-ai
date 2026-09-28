from pathlib import Path

def test_settings_refresh_does_not_probe_by_default():
    text=Path('ui/settings_panel.py').read_text(encoding='utf-8')
    assert 'self.refresh_model_view()' in text
    assert 'def refresh_model_view(self,probe=False)' in text
