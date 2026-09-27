from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Any
from core.permissions import PermissionEngine

class Risk(IntEnum):
    READ_ONLY=0
    REVERSIBLE=1
    EXTERNAL_SIDE_EFFECT=2
    DESTRUCTIVE=3
    CRITICAL=4

@dataclass
class Tool:
    name:str
    description:str
    handler:Callable[[dict[str,Any]],Any]
    risk:Risk=Risk.READ_ONLY

class ToolRegistry:
    def __init__(self,settings):
        self.settings=settings;self.permissions=PermissionEngine(settings.autonomy_mode);self._tools={}
    def register(self,t:Tool):
        if t.name in self._tools:raise ValueError(f'Duplicate tool {t.name}')
        self._tools[t.name]=t
    def get(self,name):return self._tools[name]
    def all(self):return list(self._tools.values())
    def schema_text(self):return '\n'.join(f'- {t.name}: {t.description}; risk={t.risk.name}' for t in self._tools.values())
    def set_autonomy_mode(self,mode:str):
        mode=str(mode).lower().strip()
        if mode not in {'observe','suggest','ask','act'}:raise ValueError('invalid autonomy mode')
        self.permissions.mode=mode;return mode
    @property
    def autonomy_mode(self):return self.permissions.mode
    def automatic(self,t:Tool):return self.permissions.decide(int(t.risk),confirmed=False).allowed
    def authorize(self,t:Tool,confirmed:bool=False):return self.permissions.decide(int(t.risk),confirmed=confirmed)
