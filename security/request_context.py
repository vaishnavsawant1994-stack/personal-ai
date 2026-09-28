from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class TrustedRequestContext:
    device_id: str
    session_id: str
    reauthenticated_at: float | None = None


_current: ContextVar[TrustedRequestContext | None] = ContextVar(
    'personal_ai_trusted_request_context',
    default=None,
)


def current_trusted_request() -> TrustedRequestContext | None:
    return _current.get()


def set_trusted_request(context: TrustedRequestContext) -> Token:
    return _current.set(context)


def reset_trusted_request(token: Token) -> None:
    _current.reset(token)
