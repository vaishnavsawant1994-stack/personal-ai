from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from desktop.input_clipboard import default_clipboard_adapter
from desktop.operator_transactions import OperatorBinding,OperatorTransactionStore
from desktop.safe_desktop_operator import DesktopAction,SafeDesktopOperator
from tools.registry import Risk,Tool


def _action(parameters):
    allowed={f.name for f in fields(DesktopAction)}
    return DesktopAction(**{k:v for k,v in dict(parameters or {}).items() if k in allowed})


def register(reg,settings):
    data_dir=Path(settings.data_dir);transactions=OperatorTransactionStore(data_dir/'operator-transactions.sqlite3')
    def operator(parameters):
        ctx=dict(parameters.get('_trusted_context') or {})
        if not all(ctx.get(k) not in (None,'') for k in ('owner_id','device_id','session_id','security_epoch')):raise PermissionError('trusted_context_required')
        binding=OperatorBinding(str(ctx['owner_id']),str(ctx['device_id']),str(ctx['session_id']),int(ctx['security_epoch']),str(ctx.get('conversation_id') or ''),str(ctx.get('workflow_id') or ''))
        return SafeDesktopOperator(reg.policy_gateway,transactions,binding,clipboard=default_clipboard_adapter(),emergency_stop=lambda:bool(reg.emergency_stop))
    def read(parameters):
        a=_action(parameters)
        if a.kind not in SafeDesktopOperator.READ_ONLY:raise PermissionError('side_effect_requires_approved_tool')
        result=operator(parameters).execute(a)
        return result.__dict__
    def act(parameters):
        a=_action(parameters)
        if a.kind in SafeDesktopOperator.READ_ONLY:raise PermissionError('use_read_only_desktop_tool')
        # Reaching this handler means the execution-scoped Trusted Action approval
        # and required recent reauthentication were already consumed by AgentExecutor.
        result=operator(parameters).execute(a,approved=True,reauthenticated=True)
        return result.__dict__
    def verify(parameters,result):
        status=str((result or {}).get('status') or '')
        governed=status in {'verified','blocked_by_policy','cancelled','approval_required','reauthentication_required','verification_failed','recovery_review_required'}
        return {'verified':governed,'reason':'W7.5 governed outcome','evidence':{'status':status,'reason_code':str((result or {}).get('reason_code') or '')}}
    reg.register(Tool('desktop_file_read','W7.5 bounded read-only desktop/file/clipboard observation. Params follow DesktopAction and require owner/device/session context.',read,Risk.READ_ONLY,verifier=verify,requires_trusted_context=True))
    reg.register(Tool('desktop_file_act','W7.5 owner-approved desktop/file/input/clipboard action. No shell, elevation, unrestricted filesystem or background monitoring.',act,Risk.EXTERNAL_SIDE_EFFECT,verifier=verify,rollback_description='Rollback is operation-specific. Trash may have a compensating action; permanent delete is irreversible; unknown outcomes require recovery review.',verification_required=True,requires_reauth=True,minimum_risk=Risk.EXTERNAL_SIDE_EFFECT,requires_trusted_context=True))
