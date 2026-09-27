from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from typing import Any

from desktop.controller import DesktopController
from desktop.transactions import DesktopTransactionManager
from vision.screen_understanding import ScreenUnderstanding


ALLOWED_DESKTOP_ACTIONS = {'move', 'click', 'type_text', 'hotkey'}


@dataclass(frozen=True)
class ComputerPlanStep:
    kind: str
    params: dict[str, Any]
    reason: str = ''
    verify: str = ''


class ComputerIntelligence:
    """Observe → Understand → Act → Verify computer-control runtime.

    It never grants its own permission. The enclosing ToolRegistry determines
    whether execute() may run. This class additionally bounds action types/counts,
    uses transactional primitives and verifies state changes after every action.
    """

    def __init__(self, models, data_dir, *, second_brain=None, events=None, controller=None):
        self.models = models
        self.second_brain = second_brain
        self.events = events
        self.screen = ScreenUnderstanding(models, data_dir)
        self.controller = controller or DesktopController()
        self.transactions = DesktopTransactionManager(self.controller)
        self._lock = threading.RLock()

    def _emit(self, name, **payload):
        if self.events:
            self.events.emit(name, **payload)

    def observe(self, question: str = 'Describe the visible screen and the actionable UI elements relevant to the user.', monitor: int = 1):
        self._emit('state', state='understanding')
        result = self.screen.analyze(question, monitor=monitor)
        self._emit('computer.observed', screenshot=result.get('screenshot'))
        return result

    def _memory_context(self, goal: str):
        if not self.second_brain:
            return []
        try:
            return self.second_brain.context(goal, limit=5)
        except Exception:
            return []

    def plan(self, goal: str, *, observation: dict | None = None, max_steps: int = 8):
        max_steps = max(1, min(int(max_steps), 12))
        observation = observation or self.observe(
            f'Describe the current UI and identify only elements relevant to this goal: {goal}'
        )
        memory = self._memory_context(goal)
        prompt = f'''Create a cautious desktop action plan for this goal:\n{goal}\n\nCURRENT SCREEN ANALYSIS:\n{observation.get('analysis', observation)}\n\nRELEVANT PERSONAL CONTEXT:\n{json.dumps(memory, default=str)[:5000]}\n\nReturn JSON only with this shape:\n{{"summary":"...","steps":[{{"kind":"move|click|type_text|hotkey","params":{{}},"reason":"...","verify":"what should be visibly true after this action"}}]}}\nRules: at most {max_steps} steps; do not invent coordinates unless supported by the screen analysis; do not submit purchases, send messages, delete data, change security settings, or type secrets unless the user's goal explicitly requires it. Prefer the smallest reversible sequence.'''
        data = self.models.json(prompt, system='You are Personal AI computer-control planner. Return bounded JSON only.')
        raw_steps = list(data.get('steps', []))[:max_steps]
        steps = []
        for row in raw_steps:
            kind = str(row.get('kind', '')).strip()
            if kind not in ALLOWED_DESKTOP_ACTIONS:
                raise ValueError(f'unsupported computer action: {kind}')
            params = dict(row.get('params') or {})
            self._validate_params(kind, params)
            steps.append(
                ComputerPlanStep(
                    kind=kind,
                    params=params,
                    reason=str(row.get('reason', '')),
                    verify=str(row.get('verify', '')),
                )
            )
        if not steps:
            raise ValueError('computer plan contained no executable steps')
        plan = {'summary': str(data.get('summary', '')), 'steps': [step.__dict__ for step in steps]}
        self._emit('computer.planned', goal=goal, step_count=len(steps))
        return plan

    @staticmethod
    def _validate_params(kind: str, params: dict):
        if kind in {'move', 'click'}:
            for key in ('x', 'y'):
                if key in params:
                    value = int(params[key])
                    if value < -10000 or value > 10000:
                        raise ValueError(f'{key} is outside the allowed coordinate range')
                    params[key] = value
        if kind == 'type_text':
            text = str(params.get('text', ''))
            if not text or len(text) > 8000:
                raise ValueError('type_text requires 1-8000 characters')
            params['text'] = text
        if kind == 'hotkey':
            keys = list(params.get('keys') or [])
            if not 1 <= len(keys) <= 5 or any(len(str(key)) > 24 for key in keys):
                raise ValueError('hotkey requires 1-5 bounded key names')
            params['keys'] = [str(key).lower() for key in keys]

    def _semantic_verify(self, question: str, monitor: int = 1):
        if not question:
            return {'checked': False, 'verified': True, 'analysis': ''}
        prompt = (
            f'Verify this UI postcondition: {question}. '
            'Start the answer with VERIFIED or NOT_VERIFIED, then give one short reason.'
        )
        result = self.screen.analyze(prompt, monitor=monitor)
        analysis = str(result.get('analysis', ''))
        normalized = analysis.strip().upper()
        return {
            'checked': True,
            'verified': normalized.startswith('VERIFIED') and not normalized.startswith('VERIFIED NOT'),
            'analysis': analysis,
            'screenshot': result.get('screenshot'),
        }

    def execute(self, goal: str, *, plan: dict | None = None, max_steps: int = 8, monitor: int = 1, cancel_event=None):
        with self._lock:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('computer execution cancelled before start')
            initial = self.observe(f'Describe the screen before executing this goal: {goal}', monitor=monitor)
            plan = plan or self.plan(goal, observation=initial, max_steps=max_steps)
            steps = [ComputerPlanStep(**row) for row in list(plan.get('steps', []))[:max_steps]]
            tx = self.transactions.begin()
            evidence = []
            self._emit('state', state='acting')
            self._emit('computer.execution.started', transaction_id=tx.id, goal=goal, step_count=len(steps))
            try:
                for index, step in enumerate(steps):
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError('computer execution cancelled by user')
                    self._validate_params(step.kind, step.params)
                    result = self.transactions.execute(tx, step.kind, **step.params)
                    if not result.get('verified'):
                        raise RuntimeError(f'computer action did not produce a verifiable change: step {index + 1}')
                    semantic = self._semantic_verify(step.verify, monitor=monitor)
                    if semantic['checked'] and not semantic['verified']:
                        raise RuntimeError(f'computer postcondition failed at step {index + 1}: {semantic["analysis"]}')
                    evidence.append(
                        {
                            'step': index + 1,
                            'kind': step.kind,
                            'reason': step.reason,
                            'action_verified': bool(result.get('verified')),
                            'semantic_verify': semantic,
                        }
                    )
                    self._emit('computer.step.verified', transaction_id=tx.id, step=index + 1, kind=step.kind)
                final = self.observe(f'Describe the completed state for this goal: {goal}', monitor=monitor)
                committed = self.transactions.commit(tx)
                output = {
                    'ok': True,
                    'goal': goal,
                    'transaction_id': tx.id,
                    'plan': plan,
                    'evidence': evidence,
                    'final': final,
                    **committed,
                }
                self._emit('computer.execution.completed', transaction_id=tx.id, goal=goal)
                return output
            except Exception as exc:
                rollback = self.transactions.rollback(tx)
                self._emit('computer.execution.failed', transaction_id=tx.id, goal=goal, error=str(exc), rollback=rollback)
                raise
