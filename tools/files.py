from pathlib import Path
import shutil
from tools.registry import Tool, Risk

def register(reg):
    def list_dir(p):
        path=Path(str(p.get("path",Path.home()))).expanduser()
        return [{"name":x.name,"is_dir":x.is_dir(),"size":x.stat().st_size if x.is_file() else None}
                for x in list(path.iterdir())[:200]]

    def read_file(p):
        path=Path(str(p["path"])).expanduser()
        return path.read_text(encoding="utf-8",errors="replace")[:50000]

    def write_file(p):
        path=Path(str(p["path"])).expanduser(); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(str(p.get("content","")),encoding="utf-8")
        return {"ok":True,"path":str(path)}

    def copy_file(p):
        s=Path(p["source"]).expanduser(); d=Path(p["destination"]).expanduser()
        d.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(s,d)
        return {"ok":True,"destination":str(d)}

    reg.register(Tool("list_dir","List directory; params: path",list_dir,Risk.READ_ONLY))
    reg.register(Tool("read_file","Read text file; params: path",read_file,Risk.READ_ONLY))
    reg.register(Tool("write_file","Write text file; params: path, content",write_file,Risk.REVERSIBLE))
    reg.register(Tool("copy_file","Copy file; params: source, destination",copy_file,Risk.REVERSIBLE))
