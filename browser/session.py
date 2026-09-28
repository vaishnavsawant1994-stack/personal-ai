from __future__ import annotations
from pathlib import Path

from browser.observation import observe_page, safe_browser_evidence


_SENSITIVE_SELECTOR = ','.join([
    'input[type="password"]',
    'input[type="hidden"]',
    'input[autocomplete="current-password"]',
    'input[autocomplete="new-password"]',
    'input[autocomplete="one-time-code"]',
    'input[autocomplete="cc-number"]',
    'input[autocomplete="cc-csc"]',
    'input[autocomplete="cc-exp"]',
    'input[name*="token" i]',
    'input[name*="secret" i]',
    'input[name*="pass" i]',
    'input[name*="pin" i]',
    'input[name*="cvv" i]',
    'input[name*="cvc" i]',
    'input[id*="token" i]',
    'input[id*="secret" i]',
    'input[id*="pass" i]',
    'input[id*="pin" i]',
    'input[id*="cvv" i]',
    'input[id*="cvc" i]',
])


class PersistentBrowser:
    def __init__(self, profile_dir: Path, headless: bool = False):
        self.profile_dir = Path(profile_dir); self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless; self._pw = None; self.context = None; self.page = None

    def start(self):
        if self.context: return self
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(str(self.profile_dir), headless=self.headless)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def stop(self):
        if self.context: self.context.close()
        if self._pw: self._pw.stop()
        self.context = self.page = self._pw = None

    def goto(self, url, wait_until='domcontentloaded'):
        self.start(); self.page.goto(url, wait_until=wait_until); return self.snapshot()

    def snapshot(self):
        self.start(); data = observe_page(self.page)
        return {'url': data['normalized_url'], 'title': data['title'], 'text': data['visible_text'], 'domain': data['domain'], 'origin': data['origin'], 'tab_id': data['tab_id'], 'tab_index': data['tab_index'], 'tab_count': data['tab_count']}

    def observe(self):
        self.start(); return observe_page(self.page)

    def safe_observation(self):
        return safe_browser_evidence(self.observe())

    def capture_sanitized_screenshot(self) -> dict:
        """Return browser-native masked PNG bytes only; never writes an unredacted file."""
        self.start()
        masks = []
        sensitive_count = 0
        for frame in list(self.page.frames):
            try:
                locator = frame.locator(_SENSITIVE_SELECTOR)
                count = int(locator.count())
                sensitive_count += count
                if count:
                    masks.append(locator)
            except Exception:
                return {'available': False, 'reason': 'unsupported_geometry', 'sensitive_count': sensitive_count, 'bytes': b''}
        try:
            geometry = self.page.evaluate('''() => ({
                device_pixel_ratio: window.devicePixelRatio || null,
                page_zoom: (window.visualViewport && window.visualViewport.scale) || 1,
                viewport_width: window.innerWidth || null,
                viewport_height: window.innerHeight || null,
                scroll_x: window.scrollX || 0,
                scroll_y: window.scrollY || 0,
                browser_window_x: window.screenX,
                browser_window_y: window.screenY,
                browser_window_width: window.outerWidth || null,
                browser_window_height: window.outerHeight || null,
                content_offset_x: Math.max(0, ((window.outerWidth || window.innerWidth) - window.innerWidth) / 2),
                content_offset_y: Math.max(0, (window.outerHeight || window.innerHeight) - window.innerHeight)
            })''') or {}
        except Exception:
            geometry = {}
        try:
            png = self.page.screenshot(type='png', mask=masks, animations='disabled', caret='hide')
        except Exception:
            return {'available': False, 'reason': 'browser_native_capture_failed', 'sensitive_count': sensitive_count, 'bytes': b'', 'geometry': geometry}
        return {
            'available': True,
            'reason': '',
            'bytes': bytes(png),
            'redaction_status': 'sanitized',
            'redaction_method': 'browser_native_element_mask' if sensitive_count else 'browser_native_no_sensitive_elements',
            'sensitive_count': sensitive_count,
            'geometry': geometry,
            'capture_source': 'browser_native',
        }

    def click(self, selector): self.start(); self.page.locator(selector).click(); return self.snapshot()
    def fill(self, selector, value): self.start(); self.page.locator(selector).fill(value); return self.snapshot()
    def wait_for(self, selector, state='visible', timeout=10000): self.start(); self.page.locator(selector).wait_for(state=state, timeout=timeout); return True
    def verify(self, selector=None, text=None):
        self.start()
        if selector is not None: return self.page.locator(selector).count() > 0
        if text is not None: return self.page.get_by_text(text, exact=False).count() > 0
        raise ValueError('selector or text required')
