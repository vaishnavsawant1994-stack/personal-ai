from __future__ import annotations

from future_intelligence.operations_store import _utc_now


class OperationRecoveryMixin:
    def _recovery_authority(self):
        tools = self._tools()
        getter = getattr(tools, 'ensure_recovery_authority', None) if tools is not None else None
        if not callable(getter):
            raise RuntimeError('W7.6 recovery authority is unavailable')
        return getter()

    def _recovery_binding(self, authority, transaction_id: str):
        helper = getattr(authority, 'transaction_binding', None)
        if callable(helper):
            return dict(helper(transaction_id) or {})
        con_factory = getattr(authority, '_con', None)
        if not callable(con_factory):
            raise RuntimeError('W7 recovery transaction binding cannot be inspected safely')
        with con_factory() as con:
            row = con.execute(
                'SELECT owner_id,device_id,session_id,security_epoch,workflow_id FROM operator_transactions WHERE transaction_id=?',
                (str(transaction_id),),
            ).fetchone()
        if not row:
            raise KeyError('W7 recovery transaction not found')
        return dict(row)

    def _assert_recovery_binding(self, authority, transaction_id: str, operation: dict):
        binding = self._recovery_binding(authority, transaction_id)
        checks = (
            ('owner', str(operation.get('owner_id') or 'owner'), str(binding.get('owner_id') or '')),
            ('device', str(operation.get('device_id') or ''), str(binding.get('device_id') or '')),
            ('session', str(operation.get('session_id') or ''), str(binding.get('session_id') or '')),
            ('security epoch', int(operation.get('security_epoch') or 0), int(binding.get('security_epoch') or 0)),
            ('workflow', str(operation.get('operation_id') or ''), str(binding.get('workflow_id') or '')),
        )
        mismatch = next((name for name, expected, actual in checks if expected != actual), None)
        if mismatch:
            raise PermissionError(f'W7 recovery {mismatch} binding mismatch')
        return binding

    def _discover_recovery_transaction(self, operation_id: str):
        try:
            authority = self._recovery_authority()
            finder = getattr(authority, 'find_transaction_for_workflow', None)
            if callable(finder):
                value = finder(operation_id)
                return str(value) if value else None
            con_factory = getattr(authority, '_con', None)
            if not callable(con_factory):
                return None
            with con_factory() as con:
                row = con.execute(
                    'SELECT transaction_id FROM operator_transactions WHERE workflow_id=? ORDER BY updated_at DESC LIMIT 1',
                    (str(operation_id),),
                ).fetchone()
            return str(row['transaction_id'] if hasattr(row, 'keys') else row[0]) if row else None
        except Exception:
            return None

    def attach_recovery(self, operation_id: str, transaction_id: str, *, owner_id='owner', device_id=None, session_id=None):
        operation = self._delegation(operation_id)
        if not operation:
            raise KeyError('operation not found')
        self._assert_owner(operation, owner_id=owner_id, device_id=device_id, session_id=session_id)
        if operation['status'] != 'recovery_required':
            raise RuntimeError('operation is not waiting for W7 recovery')
        authority = self._recovery_authority()
        self._assert_recovery_binding(authority, transaction_id, operation)
        authority.owner_view(str(transaction_id))
        self._update_operation(operation_id, recovery_transaction_id=str(transaction_id))
        self._emit('future.operation.recovery_linked', operation_id=operation_id, recovery_transaction_id=str(transaction_id))
        return self.operation(operation_id)

    def refresh_recovery(self, operation_id: str, *, owner_id='owner', device_id=None, session_id=None):
        operation = self._delegation(operation_id)
        if not operation:
            raise KeyError('operation not found')
        self._assert_owner(operation, owner_id=owner_id, device_id=device_id, session_id=session_id)
        transaction_id = operation.get('recovery_transaction_id')
        if not transaction_id:
            raise RuntimeError('operation is not linked to a W7 recovery transaction')
        authority = self._recovery_authority()
        self._assert_recovery_binding(authority, transaction_id, operation)
        view = dict(authority.owner_view(str(transaction_id)) or {})
        recovery_state = str(view.get('recovery_state') or '').lower()
        transaction_state = str(view.get('transaction_state') or '').lower()
        compensated = any(str(item.get('state') or '').lower() == 'compensated' for item in view.get('rollback_limitations', []) if isinstance(item, dict))
        verified_success = bool(view.get('verified')) and not bool(view.get('uncertain'))
        if compensated or recovery_state in {'completed', 'verified_success'} or (transaction_state == 'completed' and verified_success):
            memory_id = self._record_outcome_memory(operation, status='RECOVERED', recovered=True)
            try:
                self.automations.budgets.release(operation['budget_run_id'], reason='W7 recovery verified')
            except Exception:
                pass
            self._update_operation(operation_id, status='recovered', outcome_state='RECOVERED', outcome_memory_id=memory_id, last_error=None, completed_at=_utc_now())
            self._emit('future.operation.recovered', operation_id=operation_id, recovery_transaction_id=transaction_id)
        elif recovery_state in {'failed', 'abandoned_by_owner'} or transaction_state == 'failed':
            self._update_operation(operation_id, status='failed', outcome_state='FAILED', last_error='W7RecoveryFailed', completed_at=_utc_now())
            self._emit('future.operation.failed', operation_id=operation_id, recovery_transaction_id=transaction_id, error_type='W7RecoveryFailed')
        elif recovery_state == 'cancelled' or transaction_state == 'cancelled':
            self._update_operation(operation_id, status='cancelled', outcome_state='CANCELLED', last_error='W7RecoveryCancelled', completed_at=_utc_now())
            self._emit('future.operation.cancelled', operation_id=operation_id, recovery_transaction_id=transaction_id, reason='w7_recovery_cancelled')
        else:
            self._update_operation(operation_id, status='recovery_required', outcome_state='UNCERTAIN', last_error='W7RecoveryInProgress')
        result = self.operation(operation_id)
        result['recovery'] = {
            'transaction_id': transaction_id,
            'transaction_state': view.get('transaction_state'),
            'recovery_state': view.get('recovery_state'),
            'uncertain_count': len(view.get('uncertain', [])),
            'verified_count': len(view.get('verified', [])),
        }
        return result
