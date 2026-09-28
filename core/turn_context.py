from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TurnContext:
    """Safe request-scoped metadata for one authoritative Personal AI turn.

    This object is context, not authority. Identity/session validation remains with
    the canonical security layer, model choice remains with P9/W8, and actions
    remain governed by P6/W7 and the owner.
    """

    request_id: str
    conversation_id: str
    owner_id: str
    device_id: str
    session_id: str
    security_epoch: int
    surface: str
    input_modality: str
    privacy_level: str = 'normal'
    risk_level: str = 'low'
    memory_refs: tuple[str, ...] = ()
    knowledge_refs: tuple[str, ...] = ()
    p7_observation_refs: tuple[str, ...] = ()
    p8_continuity_refs: tuple[str, ...] = ()
    model_routing_refs: tuple[str, ...] = ()
    p10_goal_refs: tuple[str, ...] = ()
    tool_refs: tuple[str, ...] = ()
    approval_refs: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    recovery_refs: tuple[str, ...] = ()
    started_at: str = field(default_factory=_now)


def new_turn_context(
    *,
    conversation_id: str = '',
    owner_id: str = 'owner',
    device_id: str = '',
    session_id: str = '',
    security_epoch: int = 0,
    surface: str = 'unknown',
    input_modality: str = 'text',
    privacy_level: str = 'normal',
    risk_level: str = 'low',
    request_id: str | None = None,
    **refs,
) -> TurnContext:
    allowed_refs = {
        'memory_refs', 'knowledge_refs', 'p7_observation_refs', 'p8_continuity_refs',
        'model_routing_refs', 'p10_goal_refs', 'tool_refs', 'approval_refs',
        'verification_refs', 'recovery_refs',
    }
    normalized = {
        key: tuple(str(item) for item in (refs.get(key) or ()) if str(item))
        for key in allowed_refs
    }
    return TurnContext(
        request_id=str(request_id or uuid.uuid4()),
        conversation_id=str(conversation_id or ''),
        owner_id=str(owner_id or 'owner'),
        device_id=str(device_id or ''),
        session_id=str(session_id or ''),
        security_epoch=max(0, int(security_epoch or 0)),
        surface=str(surface or 'unknown'),
        input_modality=str(input_modality or 'text'),
        privacy_level=str(privacy_level or 'normal'),
        risk_level=str(risk_level or 'low'),
        **normalized,
    )


_current: ContextVar[TurnContext | None] = ContextVar('personal_ai_turn_context', default=None)


def current_turn_context() -> TurnContext | None:
    return _current.get()


def set_turn_context(context: TurnContext) -> Token:
    return _current.set(context)


def reset_turn_context(token: Token) -> None:
    _current.reset(token)
