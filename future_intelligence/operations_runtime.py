from __future__ import annotations

import threading

from agent.executor import ConfirmationRequired, ExecutionCancelled, ReauthenticationRequired
from automation.budget import WorkflowBudgetError, WorkflowRecoveryRequired
from desktop.operator_context import reset_operator_request, set_operator_request

from future_intelligence.operations_store import _utc_now


class OperationRuntimeMixin:
    def _run(self, operation_id: str, *, reauthenticated_at=None):
        lock = self._locks.setdefault(operation_id, threading.RLock())
        if not lock.acquire(blocking=False):
            return self._delegation(operation_id)
        plan = None
        try:
            operation = self._delegation(operation_id)
            if not operation or operation['status'] not in {'queued', 'waiting_reauth', 'executing'}:
                return operation
            self._assert_security_epoch(operation)
            plan = self.plan(operation['plan_id'])
            if not plan:
                self._fail(operation_id, RuntimeError('plan missing'), uncertain=False)
                return self._delegation(operation_id)
            if self._requires_reauth(plan) and not self._fresh_reauth(reauthenticated_at):
                self._update_operation(operation_id, status='waiting_reauth', outcome_state='QUEUED', last_error='ReauthenticationRequired')
                self._emit('future.operation.waiting_reauth', operation_id=operation_id, plan_id=plan['id'])
                return self._delegation(operation_id)
            self._assert_no_resource_conflict(plan, operation_id)
            cancel_event = self._cancel_events.setdefault(operation_id, threading.Event())
            current = int(operation.get('current_step') or 0)
            while current < len(plan.get('steps', [])):
                operation = self._delegation(operation_id)
                if not operation or operation.get('status') == 'cancelled':
                    return operation
                if cancel_event.is_set():
                    raise ExecutionCancelled('operation cancelled by owner')
                if bool(getattr(self._tools(), 'emergency_stop', False)):
                    self._fail(operation_id, PermissionError('owner emergency stop is active'), uncertain=current > 0 and bool(operation['risk_summary'].get('consequential_steps')))
                    return self._delegation(operation_id)
                self.automations.budgets.check(operation['budget_run_id'], next_step=current, phase='p6_delegation')
                self._update_operation(operation_id, status='executing', outcome_state='DISPATCHED', current_step=current)
                self._mark_plan_step(plan, current, 'executing')
                self._emit('future.operation.executing', operation_id=operation_id, plan_id=plan['id'], step=current + 1)
                executor_plan = self._executor_plan(plan, current)
                token = set_operator_request(self._operator_context(operation, reauthenticated_at))
                try:
                    with self.automations.budgets.enter(operation['budget_run_id'], current, 0, 'p6_delegation'):
                        self.executor._continue(
                            f'{operation_id}:{current}',
                            plan['title'],
                            executor_plan,
                            0,
                            {},
                            [],
                            cancel_event=cancel_event,
                            device_id=operation.get('device_id'),
                            session_id=operation.get('session_id'),
                            owner_id=operation.get('owner_id') or 'owner',
                            conversation_id=None,
                            grounding='',
                            sensitivity=str(plan['steps'][current].get('sensitivity') or 'internal'),
                            reauthenticated_at=reauthenticated_at,
                        )
                finally:
                    reset_operator_request(token)
                self._mark_plan_step(plan, current, 'verified')
                current += 1
                self._update_operation(operation_id, status='verifying', outcome_state='EXECUTED', current_step=current)
                try:
                    self.automations.budgets.increment_completed_steps(operation['budget_run_id'])
                except Exception:
                    pass
                self._emit('future.operation.step_verified', operation_id=operation_id, plan_id=plan['id'], step=current)
            self._emit('future.operation.verifying', operation_id=operation_id, plan_id=plan['id'])
            self._complete_verified(operation_id)
            return self._delegation(operation_id)
        except ConfirmationRequired as approval:
            operation = self._delegation(operation_id)
            if self.automations is not None and operation:
                try:
                    self.automations.budgets.mark_approval_wait(operation['budget_run_id'])
                except Exception:
                    pass
            self._update_operation(operation_id, status='waiting_approval', outcome_state='DISPATCHED', approval_id=approval.approval_id)
            self._emit('future.operation.approval_required', operation_id=operation_id, approval_id=approval.approval_id, tool=approval.tool_name)
            return self._delegation(operation_id)
        except ReauthenticationRequired as exc:
            operation = self._delegation(operation_id)
            current = int((operation or {}).get('current_step') or 0)
            uncertain = bool(operation and current > 0 and operation.get('risk_summary', {}).get('consequential_steps'))
            if uncertain:
                self._fail(operation_id, exc, uncertain=True)
            else:
                self._update_operation(operation_id, status='waiting_reauth', outcome_state='QUEUED', last_error=type(exc).__name__)
                self._emit('future.operation.waiting_reauth', operation_id=operation_id)
            return self._delegation(operation_id)
        except WorkflowRecoveryRequired as exc:
            self._fail(operation_id, exc, uncertain=True)
            return self._delegation(operation_id)
        except WorkflowBudgetError as exc:
            operation = self._delegation(operation_id)
            uncertain = bool(operation and int(operation.get('current_step') or 0) > 0 and operation.get('risk_summary', {}).get('consequential_steps'))
            self._fail(operation_id, exc, uncertain=uncertain)
            return self._delegation(operation_id)
        except ExecutionCancelled as exc:
            operation = self._delegation(operation_id)
            if operation and operation.get('status') != 'cancelled':
                plan_now = self.plan(operation['plan_id']) or {}
                index = int(operation.get('current_step') or 0)
                step = plan_now.get('steps', [])[index] if index < len(plan_now.get('steps', [])) else {}
                uncertain = bool(
                    step.get('consequential')
                    and operation.get('outcome_state') in {'DISPATCHED', 'EXECUTED'}
                )
                if uncertain:
                    self._fail(operation_id, exc, uncertain=True)
                else:
                    self._update_operation(operation_id, status='cancelled', outcome_state='CANCELLED', completed_at=_utc_now())
            return self._delegation(operation_id)
        except Exception as exc:
            operation = self._delegation(operation_id)
            current = int((operation or {}).get('current_step') or 0)
            step = (plan.get('steps', [])[current] if plan and current < len(plan.get('steps', [])) else {})
            uncertain = bool(operation and step.get('consequential') and operation.get('outcome_state') in {'DISPATCHED', 'EXECUTED'})
            self._fail(operation_id, exc, uncertain=uncertain)
            return self._delegation(operation_id)
        finally:
            lock.release()
