"""Security package compatibility boundary.

Stage 2 preserves the legacy one-use ApprovalManager.consume() contract for
non-V1 callers while the canonical V1 path uses durable approve/dispatch/result
state.  Keep this translation narrow: it changes only the historical error
wording after a ticket has already been consumed; approval authority and state
remain owned by security.approvals.ApprovalManager.
"""

from . import approvals as _approvals


_original_approval_consume = _approvals.ApprovalManager.consume


def _consume_with_legacy_terminal_message(self, *args, **kwargs):
    try:
        return _original_approval_consume(self, *args, **kwargs)
    except PermissionError as exc:
        if str(exc) == 'approval is consumed':
            raise PermissionError(
                'approval is missing, expired, rejected, or already used'
            ) from exc
        raise


_approvals.ApprovalManager.consume = _consume_with_legacy_terminal_message
