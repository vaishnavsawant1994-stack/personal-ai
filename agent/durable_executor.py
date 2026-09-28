from __future__ import annotations

from agent.executor import (
    AgentExecutor,
    ConfirmationRequired,
    ExecutionCancelled,
    ReauthenticationRequired,
)
from security.approvals import parameter_hash
from tools.registry import Risk
import uuid


class ApprovalDispatchInProgress(RuntimeError):
    """A canonical approval already owns or may have owned dispatch."""


class ApprovalRecoveryRequired(RuntimeError):
    """An interrupted/uncertain dispatch must be verified through recovery."""


class DurableAgentExecutor(AgentExecutor):
    """Stage 2 hardening of AgentExecutor approval continuation.

    ApprovalManager remains the sole approval-decision authority. This subclass
    only changes continuation semantics: approval is persisted first, dispatch
    ownership is atomically claimed once, and completion/recovery is persisted
    before the HTTP transport can report a result.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._approval_worker_id = f'agent-{uuid.uuid4().hex}'

    def approval_result(self, approval_id: str) -> dict | None:
        record = self.approvals.record(approval_id)
        if record is None:
            return None
        ticket = record['ticket']
        return {
            'approval_id': ticket.id,
            'execution_id': ticket.execution_id,
            'tool': ticket.tool_name,
            'status': record['status'],
            'expires_at': ticket.expires_at,
            'device_id': ticket.device_id,
            'session_id': ticket.session_id,
            'security_epoch': ticket.security_epoch,
            'destination': ticket.destination,
            'data_classification': ticket.data_classification,
            'outcome': record.get('outcome'),
            'failure_code': record.get('failure_code'),
            'dispatch_started_at': record.get('dispatch_started_at'),
            'completed_at': record.get('completed_at'),
        }

    def pending_approvals_safe(self, *, owner_id: str = 'owner', device_id: str | None = None, session_id: str | None = None) -> list[dict]:
        return self.approvals.list_pending(owner_id=owner_id, device_id=device_id, session_id=session_id)

    def approval_context(self, approval_id: str):
        paused = self._load_paused(approval_id)
        record = self.approvals.record(approval_id)
        if not paused or record is None:
            return None
        ticket = record['ticket']
        if record['status'] not in self.approvals.ACTIVE_STATUSES:
            return None
        return {
            'approval_id': approval_id,
            'execution_id': paused.get('execution_id'),
            'device_id': paused.get('device_id'),
            'session_id': paused.get('session_id'),
            'conversation_id': paused.get('conversation_id'),
            'tool': ticket.tool_name,
            'expires_at': ticket.expires_at,
            'security_epoch': ticket.security_epoch,
            'destination': ticket.destination,
            'data_classification': ticket.data_classification,
            'status': record['status'],
        }

    def _approval_security_revalidate(self, approval_id, paused, tool, params, sensitivity):
        if getattr(self.tools, 'emergency_stop', False):
            self.approvals.invalidate(approval_id, 'emergency_stop_active')
            raise PermissionError('owner emergency stop is active')
        decision = self.tools.authorize(tool, confirmed=True, parameters=params, data_classification=sensitivity)
        if not decision.allowed:
            self.approvals.invalidate(approval_id, 'permission_or_policy_revoked')
            raise PermissionError(decision.reason or 'approved action is no longer permitted')

    def approve(self, approval_id: str, *, device_id: str | None = None, session_id: str | None = None, owner_id: str = 'owner', reauthenticated_at: float | None = None):
        record = self.approvals.record(approval_id)
        if record is None:
            raise PermissionError('approval is missing')
        if record['status'] == 'completed':
            outcome = record.get('outcome') or {}
            return str(outcome.get('reply') or 'Approved action already completed.')
        if record['status'] == 'recovery_required':
            raise ApprovalRecoveryRequired('approved action has an uncertain prior dispatch and requires verification/recovery')
        if record['status'] == 'dispatching':
            probe = self.approvals.begin_dispatch(approval_id, worker_id=self._approval_worker_id)
            if probe['status'] == 'recovery_required':
                raise ApprovalRecoveryRequired('approved action requires recovery after interrupted dispatch')
            raise ApprovalDispatchInProgress('approved action is already dispatching')

        paused = self._load_paused(approval_id)
        if not paused:
            raise PermissionError('approval continuation is unavailable')
        cancel_event = paused.get('cancel_event')
        self._check_cancel(cancel_event)
        index = paused['index']
        step = paused['plan']['steps'][index]
        tool = self.tools.get(step['tool'])
        params = step.get('parameters', {})
        sensitivity = paused.get('sensitivity', 'internal')
        effective_risk = self.tools.effective_risk(tool, parameters=params, data_classification=sensitivity)
        effective_reauth = reauthenticated_at if reauthenticated_at is not None else paused.get('reauthenticated_at')
        if (tool.requires_reauth or effective_risk == Risk.CRITICAL) and not self._fresh_reauthentication(effective_reauth, self.reauth_ttl_seconds):
            raise ReauthenticationRequired(tool.name, execution_id=paused['execution_id'])

        bound_device = device_id if device_id is not None else paused.get('device_id')
        bound_session = session_id if session_id is not None else paused.get('session_id')
        bound_owner = owner_id or paused.get('owner_id') or 'owner'
        destination = self.tools.destination(params)
        decision = self.approvals.approve(
            approval_id,
            paused['execution_id'],
            tool.name,
            params,
            owner_id=bound_owner,
            device_id=bound_device,
            session_id=bound_session,
            destination=destination,
            data_classification=sensitivity,
        )
        if decision['status'] == 'completed':
            outcome = decision.get('outcome') or {}
            return str(outcome.get('reply') or 'Approved action already completed.')
        if decision['status'] == 'recovery_required':
            raise ApprovalRecoveryRequired('approved action requires verification/recovery')
        if decision['status'] == 'dispatching':
            raise ApprovalDispatchInProgress('approved action is already dispatching')

        self._approval_security_revalidate(approval_id, paused, tool, params, sensitivity)
        claim = self.approvals.begin_dispatch(approval_id, worker_id=self._approval_worker_id)
        if not claim['dispatch']:
            if claim['status'] == 'completed':
                outcome = claim.get('outcome') or {}
                return str(outcome.get('reply') or 'Approved action already completed.')
            if claim['status'] == 'recovery_required':
                raise ApprovalRecoveryRequired('approved action requires verification/recovery')
            raise ApprovalDispatchInProgress(f"approved action is {claim['status']}")

        with self._lock:
            self._paused.pop(approval_id, None)
        audit = {
            'approval_id': approval_id,
            'execution_id': paused['execution_id'],
            'tool': tool.name,
            'parameter_hash': parameter_hash(params),
            'device_id': bound_device,
            'session_id': bound_session,
            'security_epoch': self.approvals.current_security_epoch(),
            'destination': destination,
            'data_classification': sensitivity,
        }
        self.memory.audit('approval', 'approved', audit)
        self._security_audit('approval', 'approved', audit)
        self.events.emit('approval.approved', **audit)
        self.memory.audit('approval', 'dispatch_started', audit)
        self.events.emit('approval.dispatch_started', **audit)

        results = paused['results']
        try:
            self._execute_step(paused['execution_id'], index, tool, params, results, cancel_event=cancel_event, sensitivity=sensitivity)
            try:
                reply = self._continue(
                    paused['execution_id'], paused['text'], paused['plan'], index + 1, results, paused['history'],
                    cancel_event=cancel_event, device_id=paused.get('device_id'), session_id=paused.get('session_id'),
                    owner_id=paused.get('owner_id', 'owner'), conversation_id=paused.get('conversation_id'),
                    grounding=paused.get('grounding', ''), sensitivity=sensitivity, reauthenticated_at=effective_reauth,
                )
            except ConfirmationRequired as next_approval:
                self.approvals.complete_dispatch(approval_id, {
                    'status': 'continued_to_approval',
                    'next_approval_id': next_approval.approval_id,
                    'verified': bool(results.get(f'step{index + 1}', {}).get('verified')),
                })
                self.memory.audit('approval', 'completed', {**audit, 'continued_to_approval': next_approval.approval_id})
                raise
            except ReauthenticationRequired:
                self.approvals.complete_dispatch(approval_id, {
                    'status': 'continued_to_reauthentication',
                    'verified': bool(results.get(f'step{index + 1}', {}).get('verified')),
                })
                raise
        except (ConfirmationRequired, ReauthenticationRequired):
            raise
        except Exception as exc:
            self.approvals.mark_recovery_required(approval_id, f'{type(exc).__name__}_after_dispatch')
            recovery_audit = {**audit, 'error_type': type(exc).__name__, 'recovery_required': True}
            self.memory.audit('recovery', 'required', recovery_audit)
            self._security_audit('recovery', 'required', recovery_audit)
            self.events.emit('approval.recovery_required', **recovery_audit)
            raise

        step_result = results.get(f'step{index + 1}', {})
        outcome = self.approvals.complete_dispatch(approval_id, {
            'status': 'completed',
            'reply': str(reply),
            'verified': bool(step_result.get('verified')),
            'verification_reason': str((step_result.get('verification') or {}).get('reason') or '')[:500],
        })
        completed_audit = {
            **audit,
            'verified': bool(outcome.get('verified')),
            'verification_reason': outcome.get('verification_reason', ''),
        }
        self.memory.audit('approval', 'completed', completed_audit)
        self._security_audit('approval', 'completed', completed_audit)
        self.events.emit('approval.completed', **completed_audit)
        return reply

    def reject(self, approval_id: str, *, device_id: str | None = None, session_id: str | None = None):
        record = self.approvals.record(approval_id)
        if record is None:
            raise PermissionError('approval is missing')
        if record['status'] == 'rejected':
            return 'Action cancelled.'
        if record['status'] != 'pending':
            raise PermissionError(f"approval is {record['status']}")
        paused = self._load_paused(approval_id)
        bound_device = device_id if device_id is not None else (paused or {}).get('device_id')
        bound_session = session_id if session_id is not None else (paused or {}).get('session_id')
        if not self.approvals.reject(approval_id, device_id=bound_device, session_id=bound_session):
            raise PermissionError('approval could not be rejected')
        with self._lock:
            self._paused.pop(approval_id, None)
        if paused:
            step = paused['plan']['steps'][paused['index']]
            audit = {
                'approval_id': approval_id,
                'execution_id': paused['execution_id'],
                'tool': step['tool'],
                'parameter_hash': parameter_hash(step.get('parameters', {})),
                'device_id': bound_device,
                'session_id': bound_session,
            }
            self.memory.audit('approval', 'rejected', audit)
            self._security_audit('approval', 'rejected', audit)
            self.events.emit('approval.rejected', **audit)
        self.events.emit('state', state='idle')
        return 'Action cancelled.'
