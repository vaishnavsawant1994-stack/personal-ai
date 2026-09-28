from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorRequestContext:
    owner_id: str
    device_id: str
    session_id: str
    security_epoch: int
    conversation_id: str = ''
    workflow_id: str = ''
    reauthenticated_at: float | None = None

    def safe_dict(self) -> dict:
        return {
            'owner_id': self.owner_id,
            'device_id': self.device_id,
            'session_id': self.session_id,
            'security_epoch': int(self.security_epoch),
            'conversation_id': self.conversation_id,
            'workflow_id': self.workflow_id,
        }


_current: ContextVar[OperatorRequestContext | None] = ContextVar('personal_ai_operator_request_context', default=None)


def current_operator_request() -> OperatorRequestContext | None:
    return _current.get()


def set_operator_request(context: OperatorRequestContext) -> Token:
    return _current.set(context)


def reset_operator_request(token: Token) -> None:
    _current.reset(token)
