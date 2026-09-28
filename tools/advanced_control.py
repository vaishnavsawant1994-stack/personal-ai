from tools.registry import Tool, Risk
from browser.session import PersistentBrowser


def _disabled(_params):
    raise PermissionError('legacy direct browser/desktop control is disabled; use governed computer execution')


def register(reg, settings):
    # Persistent browser remains an observation/evidence source for the
    # governed computer runtime. Legacy direct action tools are compatibility
    # names only and cannot execute.
    browser = PersistentBrowser(settings.data_dir / 'browser-profile', headless=settings.browser_headless)
    reg._persistent_browser = browser
    legacy = (
        ('browser_goto', Risk.EXTERNAL_SIDE_EFFECT),
        ('browser_snapshot', Risk.READ_ONLY),
        ('browser_click', Risk.EXTERNAL_SIDE_EFFECT),
        ('browser_fill', Risk.EXTERNAL_SIDE_EFFECT),
        ('browser_verify', Risk.READ_ONLY),
        ('desktop_position', Risk.READ_ONLY),
        ('desktop_move', Risk.REVERSIBLE),
        ('desktop_click', Risk.EXTERNAL_SIDE_EFFECT),
        ('desktop_type', Risk.EXTERNAL_SIDE_EFFECT),
        ('desktop_hotkey', Risk.EXTERNAL_SIDE_EFFECT),
    )
    for name, risk in legacy:
        reg.register(Tool(name, f'Legacy direct control {name} (disabled)', _disabled, risk, prohibited=True))
