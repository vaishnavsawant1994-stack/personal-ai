from types import SimpleNamespace
from tools.registry import ToolRegistry,Tool,Risk

def test_ask_mode():
    r=ToolRegistry(SimpleNamespace(autonomy_mode="ask")); assert r.automatic(Tool("r","",lambda p:None,Risk.READ_ONLY)); assert not r.automatic(Tool("w","",lambda p:None,Risk.REVERSIBLE))
