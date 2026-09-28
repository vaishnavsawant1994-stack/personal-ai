from __future__ import annotations

from dataclasses import dataclass

from core.runtime_state import RuntimeState


@dataclass(frozen=True)
class RuntimePresentation:
    state: RuntimeState
    label: str
    visual: str
    attention: str = "normal"


# Presentation-only mapping. It has no authority to transition runtime state.
PRESENTATIONS: dict[RuntimeState, RuntimePresentation] = {
    RuntimeState.IDLE: RuntimePresentation(RuntimeState.IDLE, "Ready", "idle"),
    RuntimeState.ACTIVE: RuntimePresentation(RuntimeState.ACTIVE, "Active", "active"),
    RuntimeState.LISTENING: RuntimePresentation(RuntimeState.LISTENING, "Listening", "listening"),
    RuntimeState.UNDERSTANDING: RuntimePresentation(RuntimeState.UNDERSTANDING, "Understanding", "understanding"),
    RuntimeState.THINKING: RuntimePresentation(RuntimeState.THINKING, "Thinking", "thinking"),
    RuntimeState.MEMORY_RETRIEVAL: RuntimePresentation(RuntimeState.MEMORY_RETRIEVAL, "Using memory", "memory"),
    RuntimeState.KNOWLEDGE_RETRIEVAL: RuntimePresentation(RuntimeState.KNOWLEDGE_RETRIEVAL, "Searching knowledge", "knowledge"),
    RuntimeState.TOOL_ACTION: RuntimePresentation(RuntimeState.TOOL_ACTION, "Working", "acting"),
    RuntimeState.RESPONDING: RuntimePresentation(RuntimeState.RESPONDING, "Responding", "speaking"),
    RuntimeState.NEEDS_APPROVAL: RuntimePresentation(RuntimeState.NEEDS_APPROVAL, "Needs approval", "approval", "approval"),
    RuntimeState.BACKGROUND: RuntimePresentation(RuntimeState.BACKGROUND, "Working in background", "background"),
    RuntimeState.SUCCESS: RuntimePresentation(RuntimeState.SUCCESS, "Complete", "success", "success"),
    RuntimeState.WARNING: RuntimePresentation(RuntimeState.WARNING, "Attention needed", "warning", "warning"),
    RuntimeState.ERROR: RuntimePresentation(RuntimeState.ERROR, "Unable to continue", "error", "error"),
}


def presentation_for(value: RuntimeState | str) -> RuntimePresentation | None:
    """Return a presentation only for an exact canonical state.

    Unknown/future values deliberately return None. Surfaces must keep their last
    accepted semantic state and may render a neutral diagnostic presentation;
    they must never reinterpret an unknown state as IDLE or SUCCESS.
    """
    if isinstance(value, RuntimeState):
        state = value
    else:
        try:
            state = RuntimeState(str(value).strip().upper())
        except (TypeError, ValueError):
            return None
    return PRESENTATIONS[state]
