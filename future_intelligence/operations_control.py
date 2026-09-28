from __future__ import annotations

import threading

from agent.executor import ConfirmationRequired, ReauthenticationRequired
from desktop.operator_context import reset_operator_request, set_operator_request

from future_intelligence.operations_store import _utc_now


class OperationControlMixin:
    def approve(
        self,
        operation_id: str,
        *,
        owner_id: str = 'owner',
        device_id: str | None = None,
        session_id: str | None = None,
        reauthenticated_at: float | None = None,
    ):
        lock = self._locks.setdefault(operation_id, threading.RLock())
        with lock:
            return self._approve_unlocked(
                operation_id, owner_id=owner_id, device_id=device_id, session_id=session_id,
                reauthenticated_at=reauthenticated_at,
            )

    def _approve_unlocked(
        self,
        operation_id: str,
        *,
        owner_id: str = 'owner',
        device_id: str | None = None,
        session_id: str | None = None,
        reauthenticated_at: float | None = None,
    ):
        operation = self._delegation(operation_id)
        if not operation:
            raise KeyError('operation not found')
        self._assert_owner(operation, owner_id=owner_id, device_id=device_id, session_id=session_id)
        if operation['status'] != 'waiting_approval' or not operation.get('approval_id'):
            raise PermissionError('operation is not waiting for approval')
        try:
            self._assert_security_epoch(operation)
        except PermissionError as exc:
            self._fail(operation_id, exc, uncertain=False)
            return self.operation(operation_id)
        if bool(getattr(self._tools(), 'emergency_stop', False)):
            raise PermissionError('owner emergency stop is active')
        approval_id = operation['approval_id']
        current = int(operation.get('current_step') or 0)
        token = set_operator_request(self._operator_context(operation, reauthenticated_at))
        try:
            with self.automations.budgets.enter(operation['budget_run_id'], current, 0, 'p6_approval_resume'):
                self.executor.approve(
                    approval_id,
                    owner_id=owner_id,
                    device_id=device_id,
                    session_id=session_id,
                    reauthenticated_at=reauthenticated_at,
                )
        except ConfirmationRequired as next_approval:
            try:
                self.automations.budgets.mark_approval_wait(operation['budget_run_id'])
            except Exception:
                pass
            self._update_operation(operation_id, status='waiting_approval', outcome_state='DISPATCHED', approval_id=next_approval.approval_id)
            self._emit('future.operation.approval_required', operation_id=operation_id, approval_id=next_approval.approval_id, tool=next_approval.tool_name)
            return self.operation(operation_id)
        except ReauthenticationRequired:
            self._update_operation(operation_id, status='waiting_reauth', last_error='ReauthenticationRequired')
            self._emit('future.operation.waiting_reauth', operation_id=operation_id)
            return self.operation(operation_id)
        except Exception as exc:
            self._fail(operation_id, exc, uncertain=True)
            return self.operation(operation_id)
        finally:
            reset_operator_request(token)
        plan = self.plan(operation['plan_id'])
        if plan:
            self._mark_plan_step(plan, current, 'verified')
        try:
            self.automations.budgets.increment_completed_steps(operation['budget_run_id'])
        except Exception:
            pass
        self._update_operation(operation_id, status='executing', outcome_state='EXECUTED', approval_id=None, current_step=current + 1)
        self._emit('future.operation.step_verified', operation_id=operation_id, step=current + 1)
        if current + 1 >= len((plan or {}).get('steps', [])):
            self._emit('future.operation.verifying', operation_id=operation_id, plan_id=operation['plan_id'])
            self._complete_verified(operation_id)
            return self.operation(operation_id)
        self._run(operation_id, reauthenticated_at=reauthenticated_at)
        return self.operation(operation_id)

    def reject(self, operation_id: str, *, owner_id='owner', device_id=None, session_id=None):
        lock = self._locks.setdefault(operation_id, threading.RLock())
        with lock:
            return self._reject_unlocked(operation_id, owner_id=owner_id, device_id=device_id, session_id=session_id)

    def _reject_unlocked(self, operation_id: str, *, owner_id='owner', device_id=None, session_id=None):
        operation = self._delegation(operation_id)
        if not operation:
            raise KeyError('operation not found')
        self._assert_owner(operation, owner_id=owner_id, device_id=device_id, session_id=session_id)
        if operation['status'] != 'waiting_approval' or not operation.get('approval_id'):
            raise PermissionError('operation is not waiting for approval')
        token = set_operator_request(self._operator_context(operation))
        try:
            self.executor.reject(operation['approval_id'], device_id=device_id, session_id=session_id)
        finally:
            reset_operator_request(token)
        try:
            self.automations.budgets.mark_cancelled(operation['budget_run_id'], 'Approval denied by owner')
        except Exception:
            pass
        memory_id = self._record_outcome_memory(operation, status='CANCELLED')
        self._update_operation(
            operation_id,
            status='cancelled',
            outcome_state='CANCELLED',
            approval_id=None,
            outcome_memory_id=memory_id,
            last_error='ApprovalDenied',
            completed_at=_utc_now(),
        )
        self._emit('future.operation.cancelled', operation_id=operation_id, reason='approval_denied')
        return self.operation(operation_id)

    def cancel(self, operation_id: str, *, owner_id='owner', device_id=None, session_id=None):
        event = self._cancel_events.get(operation_id)
        if event:
            event.set()
        lock = self._locks.setdefault(operation_id, threading.RLock())
        with lock:
            return self._cancel_unlocked(operation_id, owner_id=owner_id, device_id=device_id, session_id=session_id)

    def _cancel_unlocked(self, operation_id: str, *, owner_id='owner', device_id=None, session_id=None):
        operation = self._delegation(operation_id)
        if not operation:
            raise KeyError('operation not found')
        self._assert_owner(operation, owner_id=owner_id, device_id=device_id, session_id=session_id)
        if operation['status'] in self.TERMINAL or operation['status'] == 'recovery_required':
            return self.operation(operation_id)
        event = self._cancel_events.get(operation_id)
        if event:
            event.set()
        if operation['status'] == 'executing' and operation.get('risk_summary', {}).get('consequential_steps'):
            try:
                self.automations.budgets.mark_stopped(operation['budget_run_id'], 'Owner cancelled during consequential dispatch; recovery review required')
            except Exception:
                pass
            self._update_operation(operation_id, status='recovery_required', outcome_state='UNCERTAIN', last_error='OwnerCancelledDuringDispatch')
            self._emit('future.operation.recovery_required', operation_id=operation_id, reason='owner_cancelled_during_dispatch')
            return self.operation(operation_id)
        if operation['status'] == 'waiting_approval' and operation.get('approval_id'):
            token = set_operator_request(self._operator_context(operation))
            try:
                try:
                    self.executor.reject(operation['approval_id'], device_id=device_id, session_id=session_id)
                except Exception:
                    pass
            finally:
                reset_operator_request(token)
        try:
            self.automations.budgets.mark_cancelled(operation['budget_run_id'])
        except Exception:
            pass
        memory_id = self._record_outcome_memory(operation, status='CANCELLED')
        self._update_operation(
            operation_id,
            status='cancelled',
            outcome_state='CANCELLED',
            approval_id=None,
            outcome_memory_id=memory_id,
            completed_at=_utc_now(),
            last_error='OwnerCancelled',
        )
        self._emit('future.operation.cancelled', operation_id=operation_id, reason='owner_cancelled')
        return self.operation(operation_id)
