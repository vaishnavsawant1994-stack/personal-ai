from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TurnSelection:
    use_p10: bool
    reason: str
    signals: tuple[str, ...] = ()
    advisory_only: bool = False


class P10TurnSelector:
    """Bounded deterministic selection policy for conversational P10 entry.

    Selection grants no action authority. P10 may orchestrate after selection,
    while P6/W7/security continue to govern every consequential operation.
    """

    MAX_TEXT = 8000
    MULTI_STEP = re.compile(r'\b(first|then|after that|next|finally|step by step|multiple steps|multi[- ]stage|end[- ]to[- ]end)\b', re.I)
    DELEGATION = re.compile(r'\b(do this for me|handle this|complete this|carry out|execute the task|take care of|work on this)\b', re.I)
    BACKGROUND = re.compile(r'\b(background|later|overnight|keep working|continue working|monitor|when .* happens|every (day|week|hour))\b', re.I)
    COORDINATION = re.compile(r'\b(agent|agents|coordinate|delegate|dependencies|workflow|plan and execute)\b', re.I)
    SIMPLE_LOOKUP = re.compile(r'^\s*(what|who|when|where|why|how|define|explain|tell me|show me|remember)\b', re.I)
    # Verbs that normally describe work products/operations rather than ordinary
    # conversational transformations. Counting distinct verbs avoids an exact-
    # sentence special case while preserving the ordinary/single-action boundary.
    ACTION_VERBS = re.compile(r'\b(send|create|update|delete|book|schedule|publish|deploy|move|copy|email|message|upload|download|research|collect|find|gather|verify|validate|analy[sz]e|organize|organise|prepare|produce|compile|coordinate|monitor|recover|compare)\b', re.I)
    AUTONOMY_INJECTION = re.compile(r'\b(ignore (all|your|the) rules|enter (p10|autonomous) mode|enable (p10|autonomous mode)|switch to (p10|autonomous mode))\b', re.I)

    def select(self, text: str, *, explicit_background: bool = False, requested_actions: int = 0) -> TurnSelection:
        value = str(text or '').strip()[:self.MAX_TEXT]
        if not value:
            return TurnSelection(False, 'empty_turn')
        signals = []
        if self.MULTI_STEP.search(value): signals.append('multi_step_language')
        if self.DELEGATION.search(value): signals.append('delegated_work')
        if self.BACKGROUND.search(value) or explicit_background: signals.append('background_or_long_running')
        if self.COORDINATION.search(value): signals.append('coordination_or_dependencies')
        if requested_actions > 1: signals.append('multiple_governed_actions')
        action_verbs = {match.lower() for match in self.ACTION_VERBS.findall(value)}
        if len(action_verbs) >= 2: signals.append('multiple_action_verbs')
        if len(action_verbs) >= 3: signals.append('multi_stage_work_product')

        # User text naming P10/autonomous mode is not an orchestration capability.
        # It can coexist with real deterministic work signals, but never supplies one.
        if self.AUTONOMY_INJECTION.search(value) and not signals:
            return TurnSelection(False, 'autonomy_request_is_not_authority')

        strong = {'background_or_long_running', 'coordination_or_dependencies', 'multiple_governed_actions', 'multi_stage_work_product'}
        if strong.intersection(signals) or len(set(signals)) >= 2:
            return TurnSelection(True, 'bounded_policy_selected_orchestration', tuple(dict.fromkeys(signals)))
        if self.SIMPLE_LOOKUP.search(value) and not signals:
            return TurnSelection(False, 'ordinary_conversation_or_lookup')
        return TurnSelection(False, 'single_turn_execution_or_conversation', tuple(dict.fromkeys(signals)))

    def apply_advisory(self, selection: TurnSelection, *, model_suggests_p10: bool | None) -> TurnSelection:
        """Model advice is observable but cannot grant or remove P10 authority."""
        if model_suggests_p10 is None:
            return selection
        return TurnSelection(selection.use_p10, selection.reason, selection.signals + (f'model_advisory:{str(bool(model_suggests_p10)).lower()}',), advisory_only=True)
