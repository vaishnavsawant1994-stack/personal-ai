from __future__ import annotations

from typing import Any

from security.projection_redaction import sanitize_sensitive_text


class ExecutionRecoveryProjection:
    """Read-only owner projection over the existing W7 recovery authority."""
    MAX_TEXT=1000
    MAX_ITEMS=100
    _SECRET=('password','secret','credential','api_key','apikey','access_token','refresh_token','authorization','cookie','private_key','client_secret')

    def __init__(self, authority): self.authority=authority

    @classmethod
    def _safe(cls,value:Any,depth=0):
        if depth>6:return '[bounded]'
        if isinstance(value,dict):
            out={}
            for key,item in list(value.items())[:60]:
                normalized=str(key).lower().replace('-','_').replace(' ','_')
                out[str(key)]='[redacted]' if any(s in normalized for s in cls._SECRET) else cls._safe(item,depth+1)
            return out
        if isinstance(value,(list,tuple)):return [cls._safe(x,depth+1) for x in list(value)[:cls.MAX_ITEMS]]
        if isinstance(value,str):return sanitize_sensitive_text(value)[:cls.MAX_TEXT]
        if value is None or isinstance(value,(bool,int,float)):return value
        return str(value)[:cls.MAX_TEXT]

    @staticmethod
    def _semantic_state(view):
        recovery=str(view.get('recovery_state') or '')
        uncertain=bool(view.get('uncertain'))
        if uncertain or recovery in {'dispatched','verifying','recovery_review_required','partially_completed'}:
            return 'UNVERIFIED_OR_RECOVERY_REQUIRED'
        if recovery=='verified_success':return 'VERIFIED_SUCCESS'
        if recovery in {'failed','cancelled','abandoned_by_owner'}:return recovery.upper()
        if recovery in {'compensation_available','compensation_requires_approval'}:return 'COMPENSATION_PENDING'
        return recovery.upper() if recovery else 'ACTIVE'

    def detail(self,transaction_id,*,owner_id=None,device_id=None,session_id=None):
        # Visibility is fail-closed when a request binding is supplied. Read the
        # canonical W7.1 transaction binding; never infer ownership from the ID.
        if any(value is not None for value in (owner_id,device_id,session_id)):
            if not all(value for value in (owner_id,device_id,session_id)):
                return None
            try:
                tx=self.authority.transaction_binding(transaction_id)
            except Exception:
                return None
            if not tx or str(tx['owner_id'])!=str(owner_id) or str(tx['device_id'])!=str(device_id) or str(tx['session_id'])!=str(session_id):
                return None
        try:view=self.authority.owner_view(transaction_id)
        except KeyError:return None
        safe=self._safe(view)
        # Never turn dispatch into success: only canonical verification can do so.
        safe['owner_status']=self._semantic_state(safe)
        safe['verified_success']=safe['owner_status']=='VERIFIED_SUCCESS'
        safe['verification_required_for_success']=not safe['verified_success']
        return safe
