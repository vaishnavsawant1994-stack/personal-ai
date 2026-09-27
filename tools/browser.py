from browser.controller import BrowserController
from tools.registry import Tool, Risk

def register(reg):
    ctl=BrowserController(headless=False)
    reg.register(Tool("browser_navigate","Controlled browser navigation; params: url",
                      lambda p:ctl.navigate(str(p["url"])),Risk.EXTERNAL_SIDE_EFFECT))
    reg.register(Tool("browser_extract_text","Read page body through controlled browser; params: url",
                      lambda p:ctl.extract_text(str(p["url"])),Risk.READ_ONLY))
    reg.register(Tool("browser_click_text","Click visible text; params: url,text",
                      lambda p:ctl.click_text(str(p["url"]),str(p["text"])),Risk.EXTERNAL_SIDE_EFFECT))
