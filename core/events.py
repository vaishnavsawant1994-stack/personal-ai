from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Any, Callable


class EventBus:
    def __init__(self):
        self._listeners = defaultdict(list)
        self._lock = RLock()
        from core.runtime_state import RuntimeStateAuthority
        self.runtime_state = RuntimeStateAuthority(self)

    def subscribe(self, event: str, callback: Callable[[dict[str, Any]], None]):
        with self._lock:
            self._listeners[event].append(callback)

        def unsubscribe():
            with self._lock:
                listeners = self._listeners.get(event, [])
                if callback in listeners:
                    listeners.remove(callback)
        return unsubscribe

    @staticmethod
    def _turn_request_id():
        try:
            from core.turn_context import current_turn_context
            turn = current_turn_context()
            return str(turn.request_id) if turn is not None and turn.request_id else None
        except Exception:
            return None

    def emit(self, event: str, **payload):
        if 'request_id' not in payload:
            request_id = self._turn_request_id()
            if request_id:
                payload = {'request_id': request_id, **payload}
        with self._lock:
            listeners = list(self._listeners.get(event, []))
        msg = {'event': event, **payload}
        for fn in listeners:
            try:
                fn(msg)
            except Exception:
                pass
