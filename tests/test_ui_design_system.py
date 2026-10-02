"""Contract checks preventing parallel clients drifting from their shared theme."""
from pathlib import Path


def test_companion_generated_tokens_match_canonical_web_contract():
    canonical = Path('pwa/design-system.css').read_text().split('html,body {')[0]
    companion = Path('web-companion/design-system.css').read_text().split('\n', 1)[1]
    assert companion == canonical


def test_desktop_theme_preserves_readability_and_high_contrast():
    from ui.design_system import stylesheet
    normal, high = stylesheet(), stylesheet(True)
    assert 'color:#939cab' in normal
    assert 'color:#c1c7d3' in high
    assert 'border:1px solid #528cff' in high
    assert 'QPushButton:disabled' in normal


def test_desktop_all_routes_render_and_composer_icons_are_accessible(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from ui.main_window import MainWindow

    class Events:
        def subscribe(self, *_):
            return lambda: None

    class Memory:
        def graph(self):
            return {'nodes': [], 'edges': []}

    app = QApplication.instance() or QApplication([])
    window = MainWindow(events=Events(), executor=None, memory=Memory())
    window.show()
    app.processEvents()
    try:
        for name in window.NAV:
            window._show_page(name)
            app.processEvents()
            assert window.stack.currentWidget() is window.pages[name]
            assert window.pages[name].isVisible()
        assert not window.mic_btn.icon().isNull()
        assert window.conversation_mic_btn.accessibleName() == 'Start voice'
        window.voice_running = True
        window._update_voice_buttons()
        assert window.conversation_mic_btn.accessibleName() == 'Stop voice'
    finally:
        window.close()
