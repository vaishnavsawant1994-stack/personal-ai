from __future__ import annotations
from collections import defaultdict
from threading import RLock
from typing import Callable, Any

class EventBus:
    def __init__(self):
        self._listeners = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event: str, callback: Callable[[dict[str,Any]],None]):
        with self._lock:
            self._listeners[event].append(callback)
        def unsubscribe():
            with self._lock:
                listeners=self._listeners.get(event,[])
                if callback in listeners:listeners.remove(callback)
        return unsubscribe

    def emit(self, event: str, **payload):
        with self._lock:
            listeners = list(self._listeners.get(event, []))
        msg = {"event": event, **payload}
        for fn in listeners:
            try: fn(msg)
            except Exception: pass
