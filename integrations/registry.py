from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class Integration:
    id: str
    name: str
    capabilities: set[str] = field(default_factory=set)
    healthcheck: Callable[[], bool] | None = None

class IntegrationRegistry:
    def __init__(self): self._items={}

    def register(self,item:Integration):
        if item.id in self._items: raise ValueError(f"duplicate integration: {item.id}")
        self._items[item.id]=item

    def list(self):
        out=[]
        for x in self._items.values():
            healthy=None
            if x.healthcheck:
                try: healthy=bool(x.healthcheck())
                except Exception: healthy=False
            out.append({"id":x.id,"name":x.name,"capabilities":sorted(x.capabilities),"healthy":healthy})
        return out
