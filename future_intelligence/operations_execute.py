from __future__ import annotations

import threading

from future_intelligence.operations_store import _utc_now


class OperationExecuteMixin:
    def execute(
        self,
        plan_id: str,
        *,
        owner_id: str = 'owner',
        device_id: str | None = None,
        session_id: str | None = None,
        reauthenticated_at: float | None = None,
        background: bool = False,
    ):
        decision = self.gate.decision('p6')
        if not decision.allowed:
            return {'started': False, 'blocked': True, 'reason': decision.reason, 'plan': self.plan(plan_id)}
        plan = self._plans.get(plan_id)
        if not plan:
            raise KeyError('plan not found')
        if self.executor is None or self.automations is None:
            if any(step.get('consequential') for step in plan['steps']):
                plan['status'] = 'needs_approval'
                self._save_plan(plan)
                if self.events:
                    self.events.emit('future.operation.approval_required', plan_id=plan_id, title=plan['title'])
                return {'started': False, 'approval_required': True, 'plan': plan}
            plan['status'] = 'ready'
            self._save_plan(plan)
            return {'started': True, 'delegated': False, 'plan': plan, 'note': 'Execution must be delegated through the existing governed executor/automation engine.'}
        if plan.get('owner_id') != str(owner_id or 'owner'):
            raise PermissionError('plan owner mismatch')
        if not device_id or not session_id:
            raise PermissionError('trusted device and session context are required for governed delegation')
        if bool(getattr(self._tools(), 'emergency_stop', False)):
            return {'started': False, 'blocked': True, 'reason': 'owner emergency stop is active', 'plan': plan}

        existing = self._by_plan(plan_id)
        if existing:
            self._assert_owner(existing, owner_id=owner_id, device_id=device_id, session_id=session_id)
            if existing['status'] == 'waiting_reauth' and self._fresh_reauth(reauthenticated_at):
                self._run(existing['operation_id'], reauthenticated_at=reauthenticated_at)
                existing = self._delegation(existing['operation_id'])
            return {'started': existing['status'] in self.ACTIVE, 'delegated': True, 'duplicate': True, 'operation': self.operation(existing['operation_id'])}
        proposed_operation_id = self._operation_id(plan_id)
        self._assert_no_resource_conflict(plan, proposed_operation_id)
        operation, created = self._insert_operation(
            plan, owner_id=owner_id, device_id=device_id, session_id=session_id, security_epoch=self._security_epoch()
        )
        if not created:
            self._assert_owner(operation, owner_id=owner_id, device_id=device_id, session_id=session_id)
            return {'started': operation['status'] in self.ACTIVE, 'delegated': True, 'duplicate': True, 'operation': self.operation(operation['operation_id'])}
        try:
            self.automations.budgets.reserve_run(operation['budget_run_id'], 'p6-governed-delegation', plan['budget_policy'])
        except Exception:
            self._update_operation(operation['operation_id'], status='failed', outcome_state='FAILED', last_error='BudgetReservationFailed', completed_at=_utc_now())
            raise
        plan['status'] = 'delegated'
        self._save_plan(plan)
        self._emit('future.operation.queued', operation_id=operation['operation_id'], plan_id=plan_id)
        if background:
            thread = threading.Thread(
                target=self._run,
                kwargs={'operation_id': operation['operation_id'], 'reauthenticated_at': reauthenticated_at},
                daemon=True,
                name=f'p6-operation-{operation["operation_id"][:8]}',
            )
            self._threads[operation['operation_id']] = thread
            thread.start()
            return {'started': True, 'delegated': True, 'operation': self.operation(operation['operation_id'])}
        result = self._run(operation['operation_id'], reauthenticated_at=reauthenticated_at)
        return {'started': True, 'delegated': True, 'operation': self.operation(result['operation_id'])}
