from __future__ import annotations

from tools.registry import Risk,Tool


def register(reg):
    def authority():return reg.ensure_recovery_authority()
    def view(parameters):
        txid=str(parameters.get('transaction_id') or '').strip()
        if not txid:raise ValueError('transaction_id_required')
        return authority().owner_view(txid)
    def export(parameters):
        txid=str(parameters.get('transaction_id') or '').strip()
        if not txid:raise ValueError('transaction_id_required')
        return authority().export_report(txid)
    def decide(parameters):
        ctx=dict(parameters.get('_trusted_context') or {})
        required=('owner_id','device_id','session_id','security_epoch')
        if any(ctx.get(k) in (None,'') for k in required):raise PermissionError('owner_device_session_binding_required')
        txid=str(parameters.get('transaction_id') or '').strip();decision=str(parameters.get('decision') or '').strip();nonce=str(parameters.get('nonce') or '').strip()
        if not txid or not decision or not nonce:raise ValueError('transaction_id_decision_nonce_required')
        # Reaching this handler means AgentExecutor consumed the execution-scoped
        # Trusted Action approval and recent owner reauthentication.
        return authority().owner_decision(txid,owner_id=str(ctx['owner_id']),device_id=str(ctx['device_id']),session_id=str(ctx['session_id']),security_epoch=int(ctx['security_epoch']),decision=decision,nonce=nonce,reauthenticated=True,details=dict(parameters.get('details') or {}))
    reg.register(Tool('operator_recovery_view','W7.6 inspect one durable operator recovery transaction with redacted evidence and audit references.',view,Risk.READ_ONLY))
    reg.register(Tool('operator_recovery_export','W7.6 export a redacted checksummed recovery report for one transaction.',export,Risk.READ_ONLY))
    reg.register(Tool('operator_recovery_decide','W7.6 owner recovery decision: verify again, resume safe checkpoint, retry after verified no-effect, approve compensation, mark externally completed, abandon, cancel remaining, or export.',decide,Risk.DESTRUCTIVE,verification_required=True,requires_reauth=True,requires_trusted_context=True,verifier=lambda p,r:{'verified':bool((r or {}).get('decision_id')),'reason':'durable recovery decision recorded','evidence':{'decision_id':str((r or {}).get('decision_id') or ''),'state':str((r or {}).get('state') or '')}}))
