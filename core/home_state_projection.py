from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.runtime_state import RuntimeState


SAFE_STATE_LABELS = {
    RuntimeState.IDLE: 'Ready',
    RuntimeState.ACTIVE: 'Active',
    RuntimeState.LISTENING: 'Listening',
    RuntimeState.UNDERSTANDING: 'Understanding',
    RuntimeState.THINKING: 'Thinking',
    RuntimeState.MEMORY_RETRIEVAL: 'Using memory',
    RuntimeState.KNOWLEDGE_RETRIEVAL: 'Searching knowledge',
    RuntimeState.TOOL_ACTION: 'Working',
    RuntimeState.RESPONDING: 'Responding',
    RuntimeState.NEEDS_APPROVAL: 'Needs approval',
    RuntimeState.BACKGROUND: 'Working in background',
    RuntimeState.SUCCESS: 'Complete',
    RuntimeState.WARNING: 'Attention needed',
    RuntimeState.ERROR: 'Unable to continue',
}


@dataclass(frozen=True)
class HomeStateProjection:
    """Presentation-only projection of canonical RuntimeStateAuthority snapshots.

    This object never produces semantic runtime state and deliberately contains no
    execution, model, tool, memory, knowledge, approval, or authentication logic.
    """

    state: str
    sequence: int
    request_id: str | None
    label: str
    schema_version: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'state': self.state,
            'sequence': self.sequence,
            'request_id': self.request_id,
            'label': self.label,
        }


def project_home_state(snapshot) -> HomeStateProjection:
    state = snapshot.state
    if not isinstance(state, RuntimeState):
        raise ValueError('Home projection requires canonical RuntimeState')
    return HomeStateProjection(
        state=state.value,
        sequence=int(snapshot.sequence),
        request_id=snapshot.request_id,
        label=SAFE_STATE_LABELS[state],
    )
