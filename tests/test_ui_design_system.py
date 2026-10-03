"""Contract checks preventing parallel clients drifting from their shared theme."""
import re
from pathlib import Path


def test_companion_generated_tokens_match_canonical_web_contract():
    canonical = Path('pwa/design-system.css').read_text().split('html,body {')[0]
    companion = Path('web-companion/design-system.css').read_text().split('\n', 1)[1]
    assert companion == canonical
    primitive = Path('pwa/primitives.css').read_text()
    companion_primitive = Path('web-companion/primitives.css').read_text().split('\n', 1)[1]
    assert companion_primitive == primitive


def test_master_design_constitution_is_implemented_as_web_tokens_and_primitives():
    from pathlib import Path

    tokens = Path('pwa/design-system.css').read_text()
    primitives = Path('pwa/primitives.css').read_text()
    entry = Path('pwa/index.html').read_text()
    companion_entry = Path('web-companion/index.html').read_text()
    constitution = Path('docs/design/PERSONAL_AI_DESIGN_SYSTEM.md')
    for token in (
        '--pa-bg-0', '--pa-surface-1', '--pa-border-subtle', '--pa-text-primary',
        '--pa-blue', '--pa-success', '--pa-text-body', '--pa-space-4',
        '--pa-radius-md', '--pa-motion-normal', '--pa-touch-min', '--pa-z-modal',
    ):
        assert token in tokens
    for component in (
        '.pa-page', '.pa-section', '.pa-card', '.pa-group', '.pa-row',
        '.pa-button--primary', '.pa-icon-button', '.pa-search', '.pa-tabs',
        '.pa-status', '.pa-metric', '.pa-empty', '.pa-error', '.pa-skeleton',
        '.pa-switch', '.pa-check', '.pa-textarea', '.pa-segmented',
        '.pa-identity-header', '.pa-toast', '.pa-bottom-sheet', '.pa-popup-surface',
    ):
        assert component in primitives
    assert 'prefers-reduced-motion:reduce' in primitives
    assert 'env(safe-area-inset-bottom)' in primitives
    assert not re.search(r'#[0-9a-fA-F]{3,8}|rgba?\(', re.sub(r'/\*.*?\*/', '', primitives, flags=re.S))
    assert '/iphone/primitives.css' in entry
    assert '/primitives.css' in companion_entry
    assert constitution.is_file()


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


def test_desktop_settings_descriptions_do_not_force_horizontal_overflow(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication, QScrollArea
    from ui.settings_panel import SettingsPanel
    from types import SimpleNamespace

    class Preferences(dict):
        def snapshot(self):
            return dict(self)

    runtime = {
        'preferences': Preferences(),
        'telemetry': SimpleNamespace(snapshot=lambda: {}),
        'memory': SimpleNamespace(graph=lambda: {'nodes': [], 'edges': []}),
        'device_registry': SimpleNamespace(list=lambda: []),
        'plugins': SimpleNamespace(list=lambda: []),
        'backups': SimpleNamespace(backup_dir=Path('/tmp')),
    }
    app = QApplication.instance() or QApplication([])
    dialog = SettingsPanel(runtime)
    dialog.show()
    app.processEvents()
    try:
        scroll = dialog.findChild(QScrollArea)
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() > 0
    finally:
        dialog.close()
