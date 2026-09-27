from __future__ import annotations
from contextlib import contextmanager

class BrowserController:
    """Optional Playwright browser automation. Imported only when invoked."""
    def __init__(self,headless:bool=False): self.headless=headless

    @contextmanager
    def session(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Install Playwright with: pip install playwright && playwright install chromium") from exc
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=self.headless); page=browser.new_page()
            try: yield page
            finally: browser.close()

    def navigate(self,url:str):
        with self.session() as page:
            page.goto(url,wait_until="domcontentloaded",timeout=30000)
            return {"url":page.url,"title":page.title()}

    def extract_text(self,url:str,max_chars:int=20000):
        with self.session() as page:
            page.goto(url,wait_until="domcontentloaded",timeout=30000)
            return {"url":page.url,"title":page.title(),"text":page.locator("body").inner_text()[:max_chars]}

    def click_text(self,url:str,text:str):
        with self.session() as page:
            page.goto(url,wait_until="domcontentloaded",timeout=30000)
            page.get_by_text(text,exact=False).first.click(); page.wait_for_load_state("domcontentloaded")
            return {"url":page.url,"title":page.title()}
