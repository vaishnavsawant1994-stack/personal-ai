import io
from pathlib import Path

from PIL import Image

from browser.session import PersistentBrowser


class _Locator:
    def __init__(self, count): self._count = count
    def count(self): return self._count


class _Frame:
    def __init__(self, count=0, broken=False): self.count = count; self.broken = broken
    def locator(self, selector):
        if self.broken: raise RuntimeError('frame unavailable')
        return _Locator(self.count)


class _Page:
    def __init__(self, frames): self.frames = frames; self.mask = None
    def evaluate(self, script):
        return {'devicePixelRatio':2,'pageZoom':1.25,'viewportWidth':800,'viewportHeight':600,'scrollX':0,'scrollY':200,'windowX':10,'windowY':20,'outerWidth':1000,'outerHeight':800,'contentOffsetX':100,'contentOffsetY':200}
    def screenshot(self, **kwargs):
        self.mask = kwargs.get('mask')
        out=io.BytesIO(); Image.new('RGB',(20,20),'white').save(out,format='PNG'); return out.getvalue()


def _browser(tmp_path: Path, page):
    browser=PersistentBrowser(tmp_path/'profile'); browser.context=object(); browser.page=page; return browser


def test_browser_native_capture_masks_sensitive_elements_across_frames(tmp_path):
    page=_Page([_Frame(2),_Frame(3)]); result=_browser(tmp_path,page).capture_sanitized_screenshot()
    assert result['available'] is True and result['sensitive_count']==5
    assert result['redaction_status']=='sanitized' and result['redaction_method']=='browser_native_element_mask'
    assert len(page.mask)==2


def test_iframe_geometry_uncertainty_fails_closed(tmp_path):
    result=_browser(tmp_path,_Page([_Frame(1),_Frame(broken=True)])).capture_sanitized_screenshot()
    assert result['available'] is False and result['reason']=='unsupported_geometry'
