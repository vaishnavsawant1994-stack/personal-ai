from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_desktop_ui_imports_are_lazy():
    text=(ROOT/'app'/'main.py').read_text()
    assert 'from PyQt6.QtWidgets import QApplication' in text
    assert text.index('def main():') < text.index('from PyQt6.QtWidgets import QApplication')
    assert text.index('def main():') < text.index('from ui.main_window import MainWindow')

def test_cloud_entrypoint_uses_runtime_without_desktop_ui():
    text=(ROOT/'server'/'cloud_app.py').read_text()
    assert 'from app.main import build_runtime' in text
    assert 'create_app(' in text
    assert 'PyQt6' not in text
    assert 'MainWindow' not in text
