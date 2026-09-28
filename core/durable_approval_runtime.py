from __future__ import annotations

from agent.durable_executor import ApprovalDispatchInProgress, ApprovalRecoveryRequired
from agent.executor import ConfirmationRequired, ExecutionCancelled, ReauthenticationRequired
from core.personal_ai_runtime import CanonicalTurnRuntime, TurnReplayBlocked


class DurableApprovalTurnRuntime(CanonicalTurnRuntime):
    """Stage 2 approval-continuation hardening of the Stage 1 canonical runtime.

    Request/turn authority remains CanonicalTurnRuntime and its same durable
    canonical_turns store. This subclass only prevents transport races or
    recovery signals during approval from corrupting the canonical turn state.
    """

    def _approval_call(self, approval_id, callback, **kwargs):
        owner_id = self._owner(kwargs.get('owner_id', self.CANONICAL_OWNER))
        turn = self._turn_by_approval(approval_id)
        if turn is None:
            return callback(**kwargs)
        if turn['owner_id'] != owner_id:
            raise PermissionError('approval is not bound to this owner')
        if kwargs.get('device_id') and kwargs['device_id'] != turn.get('device_id'):
            raise PermissionError('approval is not bound to this device')
        if kwargs.get('session_id') and turn.get('session_id') and kwargs['session_id'] != turn.get('session_id'):
            raise PermissionError('approval is not bound to this trusted session')
        if turn.get('status') in self.TERMINAL_STATUSES:
            raise TurnReplayBlocked(f"request {turn['request_id']} is already {turn['status']}")

        tokens = self._bind_context(
            request_id=turn['request_id'],
            conversation_id=str(turn.get('conversation_id') or ''),
            owner_id=owner_id,
            device_id=turn.get('device_id'),
            session_id=turn.get('session_id'),
            surface=str(turn.get('surface') or 'device'),
            input_modality='approval',
            privacy_level=str(turn.get('privacy_level') or 'normal'),
            risk_level=str(turn.get('risk_level') or 'low'),
            refs={'approval_refs': (approval_id,), 'reauthenticated_at': kwargs.get('reauthenticated_at')},
        )
        try:
            reply = callback(**kwargs)
        except ConfirmationRequired as exc:
            self._update(turn['request_id'], 'needs_approval', approval_id=exc.approval_id)
            raise
        except ReauthenticationRequired:
            self._update(turn['request_id'], 'needs_reauthentication', error_code='reauthentication_required')
            raise
        except (ApprovalDispatchInProgress, ApprovalRecoveryRequired, TurnReplayBlocked):
            # Another trusted request owns this continuation, or W7 recovery is
            # required. Neither condition means the canonical user turn failed.
            raise
        except PermissionError:
            # Security/tampering failures must fail the approval request closed,
            # not let an attacker mutate the canonical owner's turn to FAILED.
            raise
        except Exception as exc:
            self._update(turn['request_id'], 'failed', error_code=type(exc).__name__)
            raise
        finally:
            self._reset_context(tokens)

        answer = str(reply)
        if not self._update(turn['request_id'], 'completed', assistant_text=answer):
            current = self._existing(turn['request_id'])
            if current and current.get('status') == 'cancelled':
                raise ExecutionCancelled('approval completed after owner cancellation')
            raise TurnReplayBlocked(f"request {turn['request_id']} changed state before approval completion")
        self._append(
            str(turn.get('conversation_id') or ''),
            device_id=turn.get('device_id'),
            kind='assistant_message',
            text=answer,
            event_id=f"{turn['request_id']}:assistant",
        )
        self._emit('turn.completed', request_id=turn['request_id'], conversation_id=turn.get('conversation_id'))
        return reply
