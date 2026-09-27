from tools.registry import Tool,Risk
from browser.session import PersistentBrowser
from desktop.controller import DesktopController
def register(reg,settings):
    browser=PersistentBrowser(settings.data_dir/'browser-profile',headless=settings.browser_headless); desktop=DesktopController()
    reg.register(Tool('browser_goto','Persistent browser navigate; params:url',lambda p:browser.goto(p['url']),Risk.EXTERNAL_SIDE_EFFECT))
    reg.register(Tool('browser_snapshot','Read current browser DOM text',lambda p:browser.snapshot(),Risk.READ_ONLY))
    reg.register(Tool('browser_click','Click CSS selector; params:selector',lambda p:browser.click(p['selector']),Risk.EXTERNAL_SIDE_EFFECT))
    reg.register(Tool('browser_fill','Fill selector; params:selector,value',lambda p:browser.fill(p['selector'],p['value']),Risk.EXTERNAL_SIDE_EFFECT))
    reg.register(Tool('browser_verify','Verify selector or text; params:selector|text',lambda p:browser.verify(p.get('selector'),p.get('text')),Risk.READ_ONLY))
    reg.register(Tool('desktop_position','Read mouse position',lambda p:desktop.position(),Risk.READ_ONLY))
    reg.register(Tool('desktop_move','Move pointer; params:x,y,duration',lambda p:desktop.move(p['x'],p['y'],p.get('duration',.2)),Risk.REVERSIBLE))
    reg.register(Tool('desktop_click','Click desktop; params:x,y,button',lambda p:desktop.click(p.get('x'),p.get('y'),p.get('button','left')),Risk.EXTERNAL_SIDE_EFFECT))
    reg.register(Tool('desktop_type','Type text; params:text',lambda p:desktop.type_text(p['text'],p.get('interval',.01)),Risk.EXTERNAL_SIDE_EFFECT))
    reg.register(Tool('desktop_hotkey','Press hotkey; params:keys',lambda p:desktop.hotkey(*p['keys']),Risk.EXTERNAL_SIDE_EFFECT))
