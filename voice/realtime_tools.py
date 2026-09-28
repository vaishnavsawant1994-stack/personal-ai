from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from security.approvals import parameter_hash
from security.projection_redaction import sanitize_external_value
from tools.registry import Risk


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
        self.approvals = getattr(executor, 'approvals', None)
        if self.approvals is None:
            raise RuntimeError('canonical approval authority is required for Realtime tools')

    def definitions(self):
        return [
            {
                'type': 'function',
                'name': tool.name,
                'description': tool.description,
                'parameters': {'type': 'object', 'additionalProperties': True},
            }
            for tool in self.tools.all()
            if not bool(getattr(tool, 'prohibited', False))
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
        effective_risk = self.tools.effective_risk(tool, parameters=params, data_classification='internal')
        if tool.requires_reauth or effective_risk == Risk.CRITICAL:
            return {
                'status': 'reauthentication_required',
                'ok': False,
                'tool': tool_name,
                'error': 'Fresh owner re-authentication is required before this voice action can execute.',
            }
        decision = self.tools.authorize(tool, confirmed=False, parameters=params)
        if not decision.allowed:
            execution_id = f'realtime:{call_id}'
            ticket = self.approvals.create(execution_id, tool_name, params)
            self.approvals.save_context(ticket.id, {
                'surface': 'realtime_voice',
                'call_id': call_id,
                'execution_id': execution_id,
                'tool_name': tool_name,
                'parameters': params,
            })
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
            if getattr(self.tools, 'emergency_stop', False):
                raise PermissionError('owner emergency stop is active')
            result = tool.handler(params)
            verification = self.tools.verify_result(tool, params, result)
            self.executor.memory.audit(
                'realtime_tool',
                'execute',
                {
                    'call_id': call_id,
                    'tool': tool.name,
                    'parameter_hash': parameter_hash(params),
                    'ok': True,
                    'verified': bool(verification.verified),
                    'verification_reason': str(verification.reason)[:500],
                },
            )
            self._emit(
                'voice.tool.completed',
                call_id=call_id,
                tool=tool.name,
                verified=bool(verification.verified),
            )
            return {
                'status': 'completed',
                'ok': True,
                'result': sanitize_external_value(result),
                'verified': bool(verification.verified),
                'verification_reason': str(verification.reason),
            }
        except Exception as exc:
            self.executor.memory.audit(
                'realtime_tool',
                'execute',
                {
                    'call_id': call_id,
                    'tool': tool.name,
                    'parameter_hash': parameter_hash(params),
                    'ok': False,
                    'error_type': type(exc).__name__,
                },
            )
            self._emit('voice.tool.failed', call_id=call_id, tool=tool.name, error_type=type(exc).__name__)
            return {'status': 'completed', 'ok': False, 'error': 'Tool execution failed.', 'error_type': type(exc).__name__}

    def _pending_item(self, call_id: str, approval_id: str | None = None):
        item = self.pending.get(call_id)
        if item is not None:
            if approval_id is not None and item.ticket_id != approval_id:
                raise PermissionError('Realtime approval identity mismatch')
            return item
        if not approval_id:
            raise PermissionError('approval_id is required after Realtime reconnect')
        context = self.approvals.context(approval_id)
        if context is None:
            record = self.approvals.record(approval_id)
            if record and record.get('status') == 'completed':
                ticket = record.get('ticket')
                outcome = record.get('outcome') or {}
                if ticket is None or ticket.execution_id != f'realtime:{call_id}':
                    raise PermissionError('Realtime completed approval identity mismatch')
                return {'completed_outcome': dict(outcome), 'approval_id': approval_id, 'call_id': call_id}
        if not context or context.get('surface') != 'realtime_voice' or context.get('call_id') != call_id:
            raise PermissionError('Realtime approval is missing or no longer active')
        item = PendingRealtimeApproval(
            call_id=call_id,
            tool_name=str(context['tool_name']),
            parameters=dict(context.get('parameters') or {}),
            created_at=time.time(),
            ticket_id=approval_id,
            execution_id=str(context['execution_id']),
        )
        return item

    def approve(self, call_id: str, approval_id: str | None = None):
        item = self._pending_item(call_id, approval_id)
        if isinstance(item, dict) and 'completed_outcome' in item:
            return dict(item['completed_outcome'])
        self.pending.pop(call_id, None)
        tool = self.tools.get(item.tool_name)
        self.approvals.approve(item.ticket_id, item.execution_id, item.tool_name, item.parameters)
        decision = self.tools.authorize(tool, confirmed=True, parameters=item.parameters)
        if not decision.allowed:
            self.approvals.invalidate(item.ticket_id, 'permission_or_policy_revoked')
            raise PermissionError(decision.reason or 'approved voice action is no longer permitted')
        claim = self.approvals.begin_dispatch(item.ticket_id, worker_id=f'realtime:{call_id}')
        if not claim.get('dispatch'):
            if claim.get('status') == 'completed':
                return dict(claim.get('outcome') or {'status': 'completed'})
            if claim.get('status') == 'recovery_required':
                raise RuntimeError('Realtime approved action requires verification/recovery')
            raise RuntimeError(f"Realtime approved action is {claim.get('status')}")
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
        try:
            result = self._execute(call_id, tool, item.parameters)
        except Exception as exc:
            self.approvals.mark_recovery_required(item.ticket_id, f'{type(exc).__name__}_after_dispatch')
            raise
        verified = bool(result.get('verified')) if result.get('ok') else False
        if not result.get('ok') and self.tools.effective_risk(
            tool, parameters=item.parameters, data_classification='internal'
        ) >= Risk.EXTERNAL_SIDE_EFFECT:
            self.approvals.mark_recovery_required(
                item.ticket_id,
                f"{result.get('error_type') or 'tool_failure'}_after_dispatch",
            )
            raise RuntimeError('Realtime approved action has an uncertain post-dispatch outcome; recovery review is required')
        outcome = {'status': 'completed', **result, 'verified': verified}
        self.approvals.complete_dispatch(item.ticket_id, outcome)
        return outcome

    def reject(self, call_id: str, approval_id: str | None = None):
        item = self._pending_item(call_id, approval_id)
        self.pending.pop(call_id, None)
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
        candidates = {call_id: item for call_id, item in self.pending.items()}
        try:
            for row in self.approvals.list_pending(owner_id='owner'):
                approval_id = row.get('approval_id') or row.get('id')
                if not approval_id:
                    continue
                context = self.approvals.context(approval_id)
                if not context or context.get('surface') != 'realtime_voice':
                    continue
                call_id = str(context.get('call_id') or '')
                if not call_id or call_id in candidates:
                    continue
                candidates[call_id] = PendingRealtimeApproval(
                    call_id=call_id,
                    tool_name=str(context.get('tool_name') or ''),
                    parameters=dict(context.get('parameters') or {}),
                    created_at=time.time(),
                    ticket_id=str(approval_id),
                    execution_id=str(context.get('execution_id') or ''),
                )
        except Exception:
            pass
        for call_id, item in candidates.items():
            self.pending.pop(call_id, None)
            try:
                self.approvals.reject(item.ticket_id)
            except Exception:
                continue
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
