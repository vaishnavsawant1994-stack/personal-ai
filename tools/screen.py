from pathlib import Path
from tools.registry import Tool, Risk

def register(reg, data_dir):
    def shot(p):
        import mss
        from PIL import Image
        path=Path(p.get("path", data_dir/"screenshots"/"latest.png")).expanduser(); path.parent.mkdir(parents=True,exist_ok=True)
        with mss.mss() as sct:
            mon=sct.monitors[int(p.get("monitor",1))]; raw=sct.grab(mon); Image.frombytes("RGB", raw.size, raw.rgb).save(path)
        return {"ok":True,"path":str(path)}
    reg.register(Tool("screenshot","Capture monitor screenshot; params: path, monitor",shot,Risk.READ_ONLY))
