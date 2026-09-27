from __future__ import annotations

import json
import threading
import time
import uuid

from agent.planner import Planner
from security.approvals import ApprovalManager, parameter_hash


class ConfirmationRequired(RuntimeError):
    def __init__(self, tool_name, parameters, description='', *, approval_id: str, execution_id: str, expires_at: float):
        super().__init__(f'Confirmation required for {tool_name}')
        self.tool_name = tool_name
        self.parameters = parameters
        self.description = description
        self.approval_id = approval_id
        self.execution_id = execution_id
        self.expires_at = expires_at


class ExecutionCancelled(RuntimeError):
    """Cooperative turn cancellation used by voice barge-in and long workflows."""


class AgentExecutor:
    def __init__(self, *, models, tools, memory, events, second_brain=None, approval_ttl_seconds: int = 300, telemetry=None):
        self.models = models
        self.tools = tools
        self.memory = memory
        self.events = events
        self.second_brain = second_brain
        self.planner = Planner(models, tools)
        self.approvals = ApprovalManager(approval_ttl_seconds)
        self._paused = {}
        self._lock = threading.RLock()
        self.telemetry = telemetry

    def _observe(self, name, start):
        if self.telemetry:
            self.telemetry.observe(name, (time.perf_counter() - start) * 1000)

    @staticmethod
    def _check_cancel(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutionCancelled('execution cancelled by the user')

    def chat(self, text, *, confirmed_tools: set[str] | None = None, cancel_event=None, device_id: str | None = None):
        turn_start = time.perf_counter()
        try:
            return self._chat(
                text,
                confirmed_tools=confirmed_tools,
                cancel_event=cancel_event,
                device_id=device_id,
            )
        except ExecutionCancelled:
            self.memory.audit('agent', 'cancelled', {'source': 'cooperative_cancel', 'device_id': device_id})
            self.events.emit('agent.cancelled', device_id=device_id)
            self.events.emit('state', state='listening')
            raise
        finally:
            self._observe('agent.turn_ms', turn_start)

    def _chat(self, text, *, confirmed_tools=None, cancel_event=None, device_id=None):
        if confirmed_tools:
            raise PermissionError('tool-name approvals are disabled; use the execution-scoped approval flow')
        self._check_cancel(cancel_event)
        self.memory.add_message('user', text)
        self.events.emit('conversation.user', text=text, device_id=device_id)
        if self.second_brain:
            self.events.emit('state', state='memory')
            memories = self.second_brain.context(text, 6)
        else:
            memories = []
        self._check_cancel(cancel_event)
        history = self.memory.recent_messages(16)
        context = json.dumps(memories, default=str)[:8000] if memories else ''
        self.events.emit('state', state='thinking')
        start = time.perf_counter()
        try:
            plan = self.planner.plan(text, context=context)
            self._observe('agent.plan_ms', start)
        except ExecutionCancelled:
            raise
        except Exception:
            self._observe('agent.plan_ms', start)
            self._check_cancel(cancel_event)
            start = time.perf_counter()
            answer = self.models.chat(text, history=history[:-1])
            self._observe('model.chat_ms', start)
            self._check_cancel(cancel_event)
            self.memory.add_message('assistant', answer)
            self.events.emit('conversation.assistant', text=answer, device_id=device_id)
            self.events.emit('state', state='speaking')
            return answer
        execution_id = str(uuid.uuid4())
        return self._continue(
            execution_id,
            text,
            plan,
            0,
            {},
            history,
            cancel_event=cancel_event,
            device_id=device_id,
        )

    def _continue(self, execution_id, text, plan, index, results, history, *, cancel_event=None, device_id=None):
        steps = plan.get('steps', [])
        while index < len(steps):
            self._check_cancel(cancel_event)
            step = steps[index]
            tool = self.tools.get(step['tool'])
            params = step.get('parameters', {})
            decision = self.tools.authorize(tool, confirmed=False)
            if not decision.allowed:
                ticket = self.approvals.create(execution_id, tool.name, params)
                with self._lock:
                    self._paused[ticket.id] = {
                        'execution_id': execution_id,
                        'text': text,
                        'plan': plan,
                        'index': index,
                        'results': dict(results),
                        'history': history,
                        'cancel_event': cancel_event,
                        'device_id': device_id,
                    }
                audit = {
                    'approval_id': ticket.id,
                    'execution_id': execution_id,
                    'tool': tool.name,
                    'parameter_hash': ticket.parameter_hash,
                    'expires_at': ticket.expires_at,
                    'device_id': device_id,
                }
                self.memory.audit('approval', 'required', audit)
                self.events.emit('approval.required', **audit)
                raise ConfirmationRequired(
                    tool.name,
                    params,
                    step.get('description', ''),
                    approval_id=ticket.id,
                    execution_id=execution_id,
                    expires_at=ticket.expires_at,
                )
            self._execute_step(execution_id, index, tool, params, results, cancel_event=cancel_event)
            index += 1
        self._check_cancel(cancel_event)
        return self._finalize(
            text,
            results,
            history,
            cancel_event=cancel_event,
            device_id=device_id,
        )

    def _execute_step(self, execution_id, index, tool, params, results, *, cancel_event=None):
        self._check_cancel(cancel_event)
        self.events.emit('state', state='acting', tool=tool.name, execution_id=execution_id)
        start = time.perf_counter()
        try:
            result = tool.handler(params)
            self._observe(f'tool.{tool.name}.ms', start)
            self._check_cancel(cancel_event)
            results[f'step{index + 1}'] = {'ok': True, 'result': result}
            self.memory.audit(
                'tool',
                'execute',
                {
                    'execution_id': execution_id,
                    'tool': tool.name,
                    'params': params,
                    'parameter_hash': parameter_hash(params),
                    'ok': True,
                },
            )
        except ExecutionCancelled:
            self.memory.audit(
                'tool',
                'cancelled_after_dispatch',
                {'execution_id': execution_id, 'tool': tool.name, 'parameter_hash': parameter_hash(params)},
            )
            raise
        except Exception as exc:
            self._observe(f'tool.{tool.name}.ms', start)
            if self.telemetry:
                self.telemetry.increment(f'tool.{tool.name}.errors')
            self.memory.audit(
                'tool',
                'execute',
                {
                    'execution_id': execution_id,
                    'tool': tool.name,
                    'params': params,
                    'parameter_hash': parameter_hash(params),
                    'ok': False,
                    'error': str(exc),
                },
            )
            raise

    def approve(self, approval_id: str):
        with self._lock:
            paused = self._paused.get(approval_id)
        if not paused:
            raise PermissionError('approval is missing, expired, rejected, or already used')
        cancel_event = paused.get('cancel_event')
        self._check_cancel(cancel_event)
        index = paused['index']
        step = paused['plan']['steps'][index]
        tool = self.tools.get(step['tool'])
        params = step.get('parameters', {})
        self.approvals.consume(approval_id, paused['execution_id'], tool.name, params)
        with self._lock:
            self._paused.pop(approval_id, None)
        self.memory.audit(
            'approval',
            'approved',
            {
                'approval_id': approval_id,
                'execution_id': paused['execution_id'],
                'tool': tool.name,
                'parameter_hash': parameter_hash(params),
                'device_id': paused.get('device_id'),
            },
        )
        self.events.emit(
            'approval.approved',
            approval_id=approval_id,
            execution_id=paused['execution_id'],
            tool=tool.name,
            device_id=paused.get('device_id'),
        )
        results = paused['results']
        self._execute_step(paused['execution_id'], index, tool, params, results, cancel_event=cancel_event)
        return self._continue(
            paused['execution_id'],
            paused['text'],
            paused['plan'],
            index + 1,
            results,
            paused['history'],
            cancel_event=cancel_event,
            device_id=paused.get('device_id'),
        )

    def reject(self, approval_id: str):
        with self._lock:
            paused = self._paused.pop(approval_id, None)
        self.approvals.reject(approval_id)
        if paused:
            step = paused['plan']['steps'][paused['index']]
            self.memory.audit(
                'approval',
                'rejected',
                {
                    'approval_id': approval_id,
                    'execution_id': paused['execution_id'],
                    'tool': step['tool'],
                    'parameter_hash': parameter_hash(step.get('parameters', {})),
                    'device_id': paused.get('device_id'),
                },
            )
            self.events.emit(
                'approval.rejected',
                approval_id=approval_id,
                execution_id=paused['execution_id'],
                tool=step['tool'],
                device_id=paused.get('device_id'),
            )
        self.events.emit('state', state='idle')
        return 'Action cancelled.'

    def _finalize(self, text, results, history, *, cancel_event=None, device_id=None):
        self._check_cancel(cancel_event)
        start = time.perf_counter()
        if results:
            answer = self.models.chat(
                f"User request: {text}\nTool results: {json.dumps(results, default=str)[:12000]}\nSummarize what was completed and mention any limitations.",
                system='You are a concise personal AI assistant.',
            )
        else:
            answer = self.models.chat(text, history=history[:-1])
        self._observe('model.chat_ms', start)
        self._check_cancel(cancel_event)
        self.memory.add_message('assistant', answer)
        self.events.emit('conversation.assistant', text=answer, device_id=device_id)
        if self.second_brain:
            for candidate in self.second_brain.extract_candidates(text, answer):
                self.second_brain.remember(candidate)
        self.events.emit('state', state='speaking')
        return answer
