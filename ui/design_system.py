"""Shared desktop presentation contract, aligned with the web semantic tokens.

Native widgets use solid surfaces for legibility and platform performance. The
original PulseWidget renderer is intentionally independent of this theme.
"""
COLORS = {
    'root': '#08090d', 'primary': '#0b0d12', 'secondary': '#101319',
    'tertiary': '#151820', 'text': '#f4f7ff', 'secondary_text': '#c1c7d3',
    'muted': '#939cab', 'accent': '#3d7dff', 'accent_hover': '#528cff',
    'border': '#242a34', 'danger': '#ff9caf',
}


def stylesheet(high_contrast=False):
    p = dict(COLORS)
    if high_contrast:
        p.update(muted='#c1c7d3', border='#636c7c')
    return """
QWidget {background:%(root)s;color:%(text)s;font-family:"Segoe UI",sans-serif;font-size:16px;}
QLabel {background:transparent;}
QLabel#brand {font-size:14px;font-weight:600;letter-spacing:2px;}
QLabel#muted,QLabel#heroHint,QLabel#menuCaption {color:%(muted)s;font-size:13px;}
QLabel#heroState {font-size:20px;font-weight:600;}
QLabel#pageHeading {font-size:28px;font-weight:600;}
QLabel#metric {font-size:25px;font-weight:600;}
QLabel#attention {color:#ffd58f;font-size:13px;}
QPushButton {background:transparent;border:1px solid transparent;border-radius:10px;padding:8px 12px;min-height:24px;color:%(secondary_text)s;font-size:14px;}
QPushButton:hover {background:%(tertiary)s;color:%(text)s;}
QPushButton:pressed,QPushButton:checked {background:%(tertiary)s;color:%(text)s;border-color:%(border)s;}
QPushButton:focus,QLineEdit:focus,QComboBox:focus,QPlainTextEdit:focus,QTextBrowser:focus,QTreeWidget:focus {border:1px solid %(accent_hover)s;}
QPushButton:disabled {color:#636c7c;background:%(secondary)s;}
QPushButton#send {background:%(accent)s;color:white;min-width:40px;max-width:40px;min-height:40px;max-height:40px;padding:0;border-radius:12px;}
QPushButton#send:hover {background:%(accent_hover)s;}
QPushButton#mic {min-width:40px;min-height:40px;padding:0;}
QPushButton#navAction,QPushButton#indicator {background:%(secondary)s;border-color:%(border)s;}
QLineEdit,QComboBox,QPlainTextEdit,QTreeWidget {background:%(secondary)s;color:%(text)s;border:1px solid %(border)s;border-radius:10px;padding:10px;selection-background-color:%(accent)s;}
QLineEdit,QComboBox {min-height:24px;}
QComboBox::drop-down {border:0;width:24px;}
QTextBrowser {background:%(primary)s;border:1px solid %(border)s;border-radius:12px;padding:14px;selection-background-color:%(accent)s;}
QTextBrowser#homeConversation {background:transparent;border:0;}
QFrame#composer,QFrame#card {background:%(secondary)s;border:1px solid %(border)s;border-radius:16px;}
QFrame#menuDrawer {background:%(secondary)s;border-left:1px solid %(border)s;}
QTabWidget::pane {border:0;background:%(root)s;}
QTabBar::tab {background:transparent;color:%(secondary_text)s;padding:12px;border-bottom:2px solid transparent;}
QTabBar::tab:selected {color:%(text)s;border-bottom-color:%(accent)s;}
QTabBar::tab:hover {background:%(tertiary)s;}
QHeaderView::section {background:%(secondary)s;color:%(secondary_text)s;border:0;padding:10px;font-size:13px;}
QTreeWidget::item {padding:6px;}
QTreeWidget::item:selected {background:%(tertiary)s;}
QCheckBox {spacing:10px;min-height:32px;}
QCheckBox::indicator {width:20px;height:20px;}
QScrollArea {border:0;}
QScrollBar:vertical {background:transparent;width:8px;}
QScrollBar::handle:vertical {background:%(border)s;border-radius:4px;min-height:24px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QMenu {background:%(secondary)s;border:1px solid %(border)s;padding:6px;}
QMenu::item {padding:10px 16px;}
QMenu::item:selected {background:%(tertiary)s;}
QToolTip {background:%(tertiary)s;color:%(text)s;border:1px solid %(border)s;padding:6px;}
""" % p


def icon(name):
    """Small stroke icons, shared by both desktop composers."""
    from PyQt6.QtCore import QByteArray, Qt
    from PyQt6.QtGui import QIcon, QPainter, QPixmap
    from PyQt6.QtSvg import QSvgRenderer
    paths = {
        'send': '<path d="M12 19V5M5 12l7-7 7 7"/>',
        'mic': '<rect x="8" y="3" width="8" height="12" rx="4"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8"/>',
        'menu': '<path d="M4 6h16M4 12h16M4 18h16"/>',
        'stop': '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    }
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{COLORS["text"]}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths[name]}</svg>'
    image = QPixmap(24, 24)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    return QIcon(image)
