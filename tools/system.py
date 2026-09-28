from __future__ import annotations
import platform
from tools.registry import Tool, Risk


def register(reg):
    def info(_):
        return {"platform":platform.platform(),"python":platform.python_version(),"machine":platform.machine(),"hostname":platform.node()}

    def legacy_launch_disabled(_):
        raise PermissionError('legacy process launch is disabled; use the governed W7.5 desktop launch action')

    reg.register(Tool("system_info","Read system info",info,Risk.READ_ONLY))
    reg.register(Tool(
        "launch_app",
        "Legacy direct process launch (disabled)",
        legacy_launch_disabled,
        Risk.EXTERNAL_SIDE_EFFECT,
        prohibited=True,
    ))
