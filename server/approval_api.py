from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from agent.durable_executor import ApprovalDispatchInProgress, ApprovalRecoveryRequired
from agent.executor import ConfirmationRequired, ReauthenticationRequired
from core.personal_ai_runtime import TurnReplayBlocked
from security.request_context import current_trusted_request


def approval_router(runtime, executor):
    """Owner-safe transport adapter over the durable canonical approval authority."""
    router = APIRouter(prefix='/iphone/api', tags=['approvals'])
    registry = runtime['device_registry']
    agent = runtime['agent_executor']
    turn_runtime = runtime.get('turn_runtime') or runtime.get('executor')

    def require_owner():
        context = current_trusted_request()
        if context is None:
            raise HTTPException(401, 'Trusted owner session required')
        if not registry.is_active(context.device_id):
            raise HTTPException(401, 'Trusted device is revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(context.device_id, 'ai:chat'):
            raise HTTPException(403, 'This device is not permitted to approve governed actions')
        return context

    def request_id_for_approval(approval_id: str):
        # Read-only correlation to the Stage 1 canonical turn. Approval authority
        # remains the Stage 2 durable ApprovalManager/continuation runtime.
        lookup = getattr(turn_runtime, '_turn_by_approval', None)
        try:
            turn = lookup(approval_id) if callable(lookup) else None
        except Exception:
            turn = None
        return str(turn.get('request_id')) if turn and turn.get('request_id') else None

    def terminal_result(approval_id: str):
        item = agent.approval_result(approval_id)
        if not item:
            return None
        request_id = request_id_for_approval(approval_id)
        status = item['status']
        if status == 'completed':
            outcome = item.get('outcome') or {}
            return {
                'status': 'approved',
                'reply': str(outcome.get('reply') or 'Approved action already completed.'),
                'approval_id': approval_id,
                'request_id': request_id,
                'canonical_status': 'completed',
                'replayed': True,
            }
        if status == 'rejected':
            return {
                'status': 'rejected',
                'reply': 'Action cancelled.',
                'approval_id': approval_id,
                'request_id': request_id,
                'canonical_status': 'rejected',
                'replayed': True,
            }
        return None

    @router.get('/approvals')
    def approvals_list():
        context = require_owner()
        return {
            'approvals': agent.pending_approvals_safe(
                owner_id='owner',
                device_id=context.device_id,
                session_id=context.session_id,
            )
        }

    @router.post('/approval/{approval_id}/approve')
    def approval_approve(approval_id: str):
        context = require_owner()
        replay = terminal_result(approval_id)
        if replay is not None:
            return replay
        item = agent.approval_result(approval_id)
        if item is None:
            raise HTTPException(404, {'code': 'approval_not_found', 'message': 'This approval is missing or unavailable.'})
        if item.get('device_id') not in (None, context.device_id):
            raise HTTPException(404, {'code': 'approval_not_found', 'message': 'This approval does not belong to this trusted device.'})
        if item.get('session_id') not in (None, context.session_id):
            raise HTTPException(409, {'code': 'approval_session_mismatch', 'message': 'This approval belongs to a different trusted session.'})
        request_id = request_id_for_approval(approval_id)
        try:
            reply = executor.approve(approval_id)
        except ConfirmationRequired as exc:
            return JSONResponse(status_code=202, content={
                'status': 'approval_required',
                'reply': f'The previous approved step completed, and the next governed action needs approval for {exc.tool_name}.',
                'prior_approval_id': approval_id,
                'request_id': request_id,
                'approval': {
                    'id': exc.approval_id,
                    'request_id': request_id,
                    'tool': exc.tool_name,
                    'description': exc.description or f'Use {exc.tool_name}',
                    'expires_at': exc.expires_at,
                },
            })
        except ReauthenticationRequired as exc:
            raise HTTPException(401, {'code': 'reauthentication_required', 'message': str(exc)})
        except ApprovalRecoveryRequired:
            raise HTTPException(409, {
                'code': 'approval_recovery_required',
                'message': 'The prior dispatch outcome is uncertain. Verification/recovery is required before any retry.',
            })
        except ApprovalDispatchInProgress:
            raise HTTPException(409, {
                'code': 'approval_in_progress',
                'message': 'This approved operation already has a canonical dispatch in progress.',
            })
        except TurnReplayBlocked:
            replay = terminal_result(approval_id)
            if replay is not None:
                return replay
            raise HTTPException(409, {
                'code': 'approval_turn_not_resumable',
                'message': 'The canonical turn cannot be resumed from this approval state.',
            })
        except PermissionError as exc:
            state = agent.approval_result(approval_id)
            code = 'approval_invalid'
            if state and state.get('status') == 'expired':
                code = 'approval_expired'
            elif state and state.get('status') == 'invalidated':
                code = 'approval_invalidated'
            raise HTTPException(409, {'code': code, 'message': str(exc)})
        return {
            'status': 'approved',
            'reply': str(reply),
            'approval_id': approval_id,
            'request_id': request_id,
            'canonical_status': 'completed',
            'replayed': False,
        }

    @router.post('/approval/{approval_id}/reject')
    def approval_reject(approval_id: str):
        context = require_owner()
        replay = terminal_result(approval_id)
        if replay is not None:
            return replay
        item = agent.approval_result(approval_id)
        if item is None:
            raise HTTPException(404, {'code': 'approval_not_found', 'message': 'This approval is missing or unavailable.'})
        if item.get('device_id') not in (None, context.device_id):
            raise HTTPException(404, {'code': 'approval_not_found', 'message': 'This approval does not belong to this trusted device.'})
        if item.get('session_id') not in (None, context.session_id):
            raise HTTPException(409, {'code': 'approval_session_mismatch', 'message': 'This approval belongs to a different trusted session.'})
        request_id = request_id_for_approval(approval_id)
        try:
            reply = executor.reject(approval_id)
        except TurnReplayBlocked:
            replay = terminal_result(approval_id)
            if replay is not None:
                return replay
            raise HTTPException(409, {
                'code': 'approval_turn_not_resumable',
                'message': 'The canonical turn cannot be resumed from this approval state.',
            })
        except PermissionError as exc:
            raise HTTPException(409, {'code': 'approval_invalid', 'message': str(exc)})
        return {
            'status': 'rejected',
            'reply': str(reply),
            'approval_id': approval_id,
            'request_id': request_id,
            'canonical_status': 'rejected',
            'replayed': False,
        }

    return router
