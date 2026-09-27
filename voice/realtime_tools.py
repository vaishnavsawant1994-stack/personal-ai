from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from security.approvals import ApprovalManager, parameter_hash


@dataclass
class PendingRealtimeApproval:
    call_id: str
    tool_name: str
    parameters: dict[str, Any]
    created_at: float
    ticket_id: str
    execution_id: str


class RealtimeToolBridge:
    """Maps Realtime function calls onto centralized policy and one-use approvals."""

    def __init__(self, executor, events=None):
        self.executor = executor
        self.tools = executor.tools
        self.events = events
        self.pending = {}
        self.approvals = getattr(executor, 'approvals', ApprovalManager())

    def definitions(self):
        return [
            {
                'type': 'function',
                'name': tool.name,
                'description': tool.description,
                'parameters': {'type': 'object', 'additionalProperties': True},
            }
            for tool in self.tools.all()
        ]

    def _emit(self, name, **data):
        if self.events:
            self.events.emit(name, **data)

    @staticmethod
    def parse_arguments(raw) -> dict:
        if raw in (None, ''):
            return {}
        if isinstance(raw, dict):
            return raw
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('tool arguments must be a JSON object')
        return value

    def invoke(self, call_id: str, tool_name: str, arguments, *, confirmed: bool = False):
        tool = self.tools.get(tool_name)
        params = self.parse_arguments(arguments)
        if confirmed:
            raise PermissionError('direct confirmed Realtime calls are disabled; approve the pending one-use ticket')
        decision = self.tools.authorize(tool, confirmed=False)
        if not decision.allowed:
            execution_id = f'realtime:{call_id}'
            ticket = self.approvals.create(execution_id, tool_name, params)
            self.pending[call_id] = PendingRealtimeApproval(
                call_id,
                tool_name,
                params,
                time.time(),
                ticket.id,
                execution_id,
            )
            audit = {
                'call_id': call_id,
                'approval_id': ticket.id,
                'execution_id': execution_id,
                'tool': tool_name,
                'parameter_hash': ticket.parameter_hash,
                'expires_at': ticket.expires_at,
            }
            self.executor.memory.audit('realtime_tool', 'approval_required', audit)
            self._emit(
                'voice.tool.approval_required',
                call_id=call_id,
                approval_id=ticket.id,
                tool=tool_name,
                parameters=params,
                expires_at=ticket.expires_at,
            )
            return {
                'status': 'approval_required',
                'call_id': call_id,
                'approval_id': ticket.id,
                'tool': tool_name,
            }
        return self._execute(call_id, tool, params)

    def _execute(self, call_id, tool, params):
        try:
            result = tool.handler(params)
            self.executor.memory.audit(
                'realtime_tool',
                'execute',
                {
                    'call_id': call_id,
                    'tool': tool.name,
                    'params': params,
                    'parameter_hash': parameter_hash(params),
                    'ok': True,
                },
            )
            self._emit('voice.tool.completed', call_id=call_id, tool=tool.name)
            return {'status': 'completed', 'ok': True, 'result': result}
        except Exception as exc:
            self.executor.memory.audit(
                'realtime_tool',
                'execute',
                {
                    'call_id': call_id,
                    'tool': tool.name,
                    'params': params,
                    'parameter_hash': parameter_hash(params),
                    'ok': False,
                    'error': str(exc),
                },
            )
            self._emit('voice.tool.failed', call_id=call_id, tool=tool.name, error=str(exc))
            return {'status': 'completed', 'ok': False, 'error': str(exc)}

    def approve(self, call_id: str):
        item = self.pending.pop(call_id)
        tool = self.tools.get(item.tool_name)
        self.approvals.consume(item.ticket_id, item.execution_id, item.tool_name, item.parameters)
        self.executor.memory.audit(
            'realtime_tool',
            'approved',
            {
                'call_id': call_id,
                'approval_id': item.ticket_id,
                'tool': item.tool_name,
                'parameter_hash': parameter_hash(item.parameters),
            },
        )
        return self._execute(call_id, tool, item.parameters)

    def reject(self, call_id: str):
        item = self.pending.pop(call_id)
        self.approvals.reject(item.ticket_id)
        self.executor.memory.audit(
            'realtime_tool',
            'rejected',
            {
                'call_id': call_id,
                'approval_id': item.ticket_id,
                'tool': item.tool_name,
                'parameter_hash': parameter_hash(item.parameters),
            },
        )
        self._emit('voice.tool.rejected', call_id=call_id, tool=item.tool_name)
        return {'status': 'completed', 'ok': False, 'error': 'user rejected action'}

    def cancel_unapproved(self, *, reason: str = 'cancelled'):
        """Invalidate voice approvals that have not been explicitly accepted yet."""
        cancelled = []
        for call_id in list(self.pending):
            item = self.pending.pop(call_id)
            try:
                self.approvals.reject(item.ticket_id)
            except Exception:
                pass
            self.executor.memory.audit(
                'realtime_tool',
                'cancelled',
                {
                    'call_id': call_id,
                    'approval_id': item.ticket_id,
                    'tool': item.tool_name,
                    'reason': reason,
                    'parameter_hash': parameter_hash(item.parameters),
                },
            )
            self._emit('voice.tool.cancelled', call_id=call_id, tool=item.tool_name, reason=reason)
            cancelled.append(call_id)
        return cancelled
