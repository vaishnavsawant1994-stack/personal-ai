from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum

class ActionRisk(IntEnum):
    READ_ONLY = 0
    REVERSIBLE = 1
    EXTERNAL_SIDE_EFFECT = 2
    DESTRUCTIVE = 3
    CRITICAL = 4

@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str

class PermissionEngine:
    """Authoritative policy layer below the LLM/tool planner."""
    def __init__(self, mode: str = "ask"):
        self.mode = mode

    def decide(self, risk: int, *, confirmed: bool = False) -> PermissionDecision:
        r = ActionRisk(int(risk))
        mode = self.mode
        if confirmed:
            return PermissionDecision(True, False, "explicitly confirmed")
        if mode == "observe":
            return PermissionDecision(r == ActionRisk.READ_ONLY, r != ActionRisk.READ_ONLY,
                                      "observe mode blocks side effects")
        if mode == "suggest":
            return PermissionDecision(r == ActionRisk.READ_ONLY, r != ActionRisk.READ_ONLY,
                                      "suggest mode blocks side effects")
        if mode == "ask":
            if r == ActionRisk.READ_ONLY:
                return PermissionDecision(True, False, "read-only action")
            return PermissionDecision(False, True, "confirmation required")
        if mode == "act":
            if r <= ActionRisk.REVERSIBLE:
                return PermissionDecision(True, False, "allowed by act mode")
            return PermissionDecision(False, True, "high-risk action requires confirmation")
        return PermissionDecision(False, True, "unknown autonomy mode")

    def authorize(self, risk: int, *, confirmed: bool = False) -> None:
        decision = self.decide(risk, confirmed=confirmed)
        if not decision.allowed:
            raise PermissionError(decision.reason)
