from __future__ import annotations

from typing import Any

from memory.second_brain import MemoryCandidate

from future_intelligence.operations_store import _utc_now


class OperationOutcomeMixin:
    def _record_outcome_memory(self, operation, *, status: str, recovered: bool = False):
        if self.second_brain is None:
            return None
        state = str(status).upper()
        candidate = MemoryCandidate(
            type='event',
            subject=f'Operation {operation["operation_id"][:8]} {state.lower()}',
            content=f'Governed operation {operation["operation_id"]} outcome: {state}.',
            confidence=1.0,
            source='personal-operations',
            verified=state == 'VERIFIED',
            tags=['p6', 'governed-operation', state.lower()],
            importance=0.55,
            sensitivity='normal',
            evidence=[],
            metadata={
                'operation_id': operation['operation_id'],
                'plan_id': operation['plan_id'],
                'outcome_state': state,
                'recovered': bool(recovered),
            },
        )
        try:
            return self.second_brain.remember(candidate)
        except Exception:
            return None
    def _complete_verified(self, operation_id: str):
        operation = self._delegation(operation_id)
        if not operation:
            return
        memory_id = self._record_outcome_memory(operation, status='VERIFIED')
        if operation.get('everyday_item_id') and self.everyday is not None:
            try:
                self.everyday.complete(operation['everyday_item_id'])
            except Exception:
                pass
        if self.automations is not None:
            try:
                self.automations.budgets.release(operation['budget_run_id'], reason='P6 operation verified')
            except Exception:
                pass
        self._update_operation(
            operation_id,
            status='verified',
            outcome_state='VERIFIED',
            approval_id=None,
            outcome_memory_id=memory_id,
            completed_at=_utc_now(),
            last_error=None,
        )
        self._emit('future.operation.completed', operation_id=operation_id, plan_id=operation['plan_id'], outcome_state='VERIFIED')
    def _fail(self, operation_id: str, exc: Exception, *, uncertain: bool):
        operation = self._delegation(operation_id)
        if not operation:
            return
        state = 'recovery_required' if uncertain else 'failed'
        outcome = 'UNCERTAIN' if uncertain else 'FAILED'
        if self.automations is not None:
            try:
                if uncertain:
                    self.automations.budgets.mark_stopped(operation['budget_run_id'], 'P6 recovery review required')
                else:
                    self.automations.budgets.release(operation['budget_run_id'], reason='P6 operation failed')
            except Exception:
                pass
        memory_id = self._record_outcome_memory(operation, status=outcome)
        recovery_transaction_id = self._discover_recovery_transaction(operation_id) if uncertain else None
        self._update_operation(
            operation_id,
            status=state,
            outcome_state=outcome,
            outcome_memory_id=memory_id,
            recovery_transaction_id=recovery_transaction_id,
            approval_id=None,
            last_error=type(exc).__name__,
            completed_at=_utc_now() if not uncertain else None,
        )
        self._emit(
            'future.operation.recovery_required' if uncertain else 'future.operation.failed',
            operation_id=operation_id,
            plan_id=operation['plan_id'],
            error_type=type(exc).__name__,
            outcome_state=outcome,
        )
    def operation(self, operation_id: str, *, owner_id=None, device_id=None, session_id=None):
        operation = self._delegation(operation_id)
        if not operation:
            return None
        if any(value is not None for value in (owner_id, device_id, session_id)):
            if not all(value is not None for value in (owner_id, device_id, session_id)):
                return None
            try:
                self._assert_owner(
                    operation,
                    owner_id=owner_id,
                    device_id=device_id,
                    session_id=session_id,
                )
            except PermissionError:
                return None
        safe = dict(operation)
        safe.pop('session_id', None)
        safe.pop('security_epoch', None)
        safe.pop('idempotency_key', None)
        safe.pop('approval_id', None)
        safe.pop('budget_run_id', None)
        safe['plan'] = self.plan_summary(operation['plan_id'])
        if self.automations is not None and operation.get('budget_run_id'):
            try:
                budget = self.automations.budgets.status(operation['budget_run_id'])
                safe['budget'] = {
                    'policy': dict(budget.get('policy') or {}),
                    'consumption': dict(budget.get('consumption') or {}),
                    'remaining': dict(budget.get('remaining') or {}),
                    'usage_state': budget.get('usage_state'),
                    'confirmed_usage': bool(budget.get('confirmed_usage')),
                    'cancellation_state': budget.get('cancellation_state'),
                    'stop_reason': budget.get('stop_reason'),
                }
            except Exception:
                safe['budget'] = None
        return safe
    def plan_summary(self, plan_id: str):
        plan = self.plan(plan_id) or {}
        if not plan:
            return None
        return {
            'id': plan.get('id'),
            'title': plan.get('title'),
            'status': plan.get('status'),
            'allowed_tools': list(plan.get('allowed_tools', [])),
            'step_count': len(plan.get('steps', [])),
            'memory_reference_count': len(plan.get('memory_ids', [])),
            'source_reference_count': len(plan.get('source_refs', [])),
            'everyday_item_id': plan.get('everyday_item_id'),
            'created_at': plan.get('created_at'),
        }
    def operations(self, *, status='all', everyday_item_id=None, limit=100, owner_id=None, device_id=None, session_id=None):
        if self._db is None:
            return []
        clauses = []
        params: list[Any] = []
        normalized = str(status or 'all').lower()
        if normalized == 'active':
            marks = ','.join('?' * len(self.ACTIVE))
            clauses.append(f'status IN ({marks})')
            params.extend(sorted(self.ACTIVE))
        elif normalized != 'all':
            clauses.append('status=?')
            params.append(normalized)
        if everyday_item_id:
            clauses.append('everyday_item_id=?')
            params.append(str(everyday_item_id))
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        params.append(max(1, min(int(limit), 1000)))
        with self._lock:
            rows = self._db.execute(
                f'SELECT operation_id FROM operation_delegations{where} ORDER BY created_at DESC LIMIT ?',
                params,
            ).fetchall()
        items = [
            self.operation(
                row['operation_id'],
                owner_id=owner_id,
                device_id=device_id,
                session_id=session_id,
            )
            for row in rows
        ]
        return [item for item in items if item is not None]
    def safe_status(self, *, owner_id=None, device_id=None, session_id=None):
        rows = self.operations(
            status='all', limit=1000,
            owner_id=owner_id, device_id=device_id, session_id=session_id,
        )
        return {
            'active': sum(1 for row in rows if row['status'] in self.ACTIVE),
            'waiting_approval': sum(1 for row in rows if row['status'] == 'waiting_approval'),
            'recovery_required': sum(1 for row in rows if row['status'] == 'recovery_required'),
            'verified': sum(1 for row in rows if row['status'] == 'verified'),
            'failed': sum(1 for row in rows if row['status'] == 'failed'),
            'recovered': sum(1 for row in rows if row['status'] == 'recovered'),
            'cancelled': sum(1 for row in rows if row['status'] == 'cancelled'),
        }
