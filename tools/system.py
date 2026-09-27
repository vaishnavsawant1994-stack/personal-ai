from __future__ import annotations
import platform, subprocess, shutil
from tools.registry import Tool, Risk

def register(reg):
    def info(_):
        return {"platform":platform.platform(),"python":platform.python_version(),"machine":platform.machine(),"hostname":platform.node()}
    def launch(p):
        app=str(p["app"]); exe=shutil.which(app)
        if not exe: raise FileNotFoundError(app)
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok":True,"executable":exe}
    reg.register(Tool("system_info","Read system info",info,Risk.READ_ONLY))
    reg.register(Tool("launch_app","Launch an executable available on PATH; params: app",launch,Risk.EXTERNAL_SIDE_EFFECT))
