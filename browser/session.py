from __future__ import annotations
from pathlib import Path
class PersistentBrowser:
    def __init__(self,profile_dir:Path,headless:bool=False): self.profile_dir=Path(profile_dir); self.profile_dir.mkdir(parents=True,exist_ok=True); self.headless=headless; self._pw=None; self.context=None; self.page=None
    def start(self):
        if self.context:return self
        from playwright.sync_api import sync_playwright
        self._pw=sync_playwright().start(); self.context=self._pw.chromium.launch_persistent_context(str(self.profile_dir),headless=self.headless); self.page=self.context.pages[0] if self.context.pages else self.context.new_page(); return self
    def stop(self):
        if self.context:self.context.close()
        if self._pw:self._pw.stop()
        self.context=self.page=self._pw=None
    def goto(self,url,wait_until='domcontentloaded'): self.start(); self.page.goto(url,wait_until=wait_until); return self.snapshot()
    def snapshot(self): self.start(); return {'url':self.page.url,'title':self.page.title(),'text':self.page.locator('body').inner_text()[:20000]}
    def click(self,selector): self.start(); self.page.locator(selector).click(); return self.snapshot()
    def fill(self,selector,value): self.start(); self.page.locator(selector).fill(value); return self.snapshot()
    def wait_for(self,selector,state='visible',timeout=10000): self.start(); self.page.locator(selector).wait_for(state=state,timeout=timeout); return True
    def verify(self,selector=None,text=None):
        self.start()
        if selector is not None:return self.page.locator(selector).count()>0
        if text is not None:return self.page.get_by_text(text,exact=False).count()>0
        raise ValueError('selector or text required')
