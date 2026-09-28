from __future__ import annotations

from desktop.operator_context import OperatorRequestContext

from future_intelligence.operations_store import _digest


class OperationRuntimeHelperMixin:
    def _fresh_reauth(self, value):
        checker = getattr(self.executor, '_fresh_reauthentication', None)
        ttl = int(getattr(self.executor, 'reauth_ttl_seconds', 300))
        return bool(checker(value, ttl)) if callable(checker) else False
    def _requires_reauth(self, plan):
        return any(bool(step.get('requires_reauth')) for step in plan.get('steps', []))
    def _resource_keys(self, plan):
        tools = self._tools()
        keys = set()
        if tools is None:
            return keys
        for step in plan.get('steps', []):
            if not step.get('consequential'):
                continue
            destination = tools.destination(step.get('parameters') or {})
            if destination:
                keys.add(_digest({'destination': destination}))
        return keys
    def _assert_no_resource_conflict(self, plan, operation_id: str):
        requested = self._resource_keys(plan)
        if not requested or self._db is None:
            return
        for other in self.operations(status='active', limit=1000):
            if other['operation_id'] == operation_id:
                continue
            other_plan = self.plan(other['plan_id'])
            if other_plan and requested.intersection(self._resource_keys(other_plan)):
                raise RuntimeError('another active consequential operation targets the same governed resource')
    def _security_epoch(self):
        approvals = getattr(self.executor, 'approvals', None)
        getter = getattr(approvals, 'current_security_epoch', None)
        return int(getter()) if callable(getter) else 0
    def _assert_security_epoch(self, operation):
        expected = int(operation.get('security_epoch') or 0)
        current = self._security_epoch()
        if expected != current:
            raise PermissionError('operation security epoch changed; create a fresh owner-authorized plan')
        return current
    def _operator_context(self, operation, reauthenticated_at=None):
        return OperatorRequestContext(
            owner_id=str(operation.get('owner_id') or 'owner'),
            device_id=str(operation.get('device_id') or ''),
            session_id=str(operation.get('session_id') or ''),
            security_epoch=int(operation.get('security_epoch') or 0),
            conversation_id='',
            workflow_id=str(operation.get('operation_id') or ''),
            reauthenticated_at=reauthenticated_at,
        )
    def _executor_plan(self, plan, step_index: int):
        step = plan['steps'][step_index]
        return {
            'goal': str(plan.get('title') or '')[:1000],
            'steps': [{
                'tool': step['requested_tool'],
                'description': str(step.get('instruction') or '')[:500],
                'parameters': dict(step.get('parameters') or {}),
            }],
        }
    def _mark_plan_step(self, plan: dict, step_index: int, status: str):
        if 0 <= int(step_index) < len(plan.get('steps', [])):
            plan['steps'][int(step_index)]['status'] = str(status)
            self._save_plan(plan)
