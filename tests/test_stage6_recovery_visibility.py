from __future__ import annotations

from recovery.visibility_projection import ExecutionRecoveryProjection


class Authority:
    def __init__(self,view):self.view=view
    def owner_view(self,transaction_id):
        if transaction_id!='tx1':raise KeyError(transaction_id)
        return self.view


def base(state='active',uncertain=None,verified=None):
    return {'transaction_id':'tx1','transaction_state':'active','recovery_state':state,'completed_steps':[],
            'current_step':'a1','affected_targets':[],'verified':verified or [],'uncertain':uncertain or [],
            'redacted_evidence':[],'proposed_recovery_options':[],'rollback_limitations':[],
            'recovery_reason':'','timestamps':{},'audit_references':[]}


def test_dispatch_is_never_projected_as_success():
    item=ExecutionRecoveryProjection(Authority(base('dispatched'))).detail('tx1')
    assert item['owner_status']=='UNVERIFIED_OR_RECOVERY_REQUIRED'
    assert item['verified_success'] is False
    assert item['verification_required_for_success'] is True


def test_unknown_or_partial_verification_stays_degraded():
    uncertain=[{'verification_id':'v1','result':'unknown_outcome','explanation':'uncertain'}]
    item=ExecutionRecoveryProjection(Authority(base('partially_completed',uncertain=uncertain))).detail('tx1')
    assert item['owner_status']=='UNVERIFIED_OR_RECOVERY_REQUIRED'
    assert not item['verified_success']


def test_only_canonical_verified_success_projects_success():
    item=ExecutionRecoveryProjection(Authority(base('verified_success',verified=[{'verification_id':'v1','result':'verified_success'}]))).detail('tx1')
    assert item['owner_status']=='VERIFIED_SUCCESS'
    assert item['verified_success'] is True
    assert item['verification_required_for_success'] is False


def test_compensation_is_distinct_and_not_rollback_success():
    item=ExecutionRecoveryProjection(Authority(base('compensation_requires_approval'))).detail('tx1')
    assert item['owner_status']=='COMPENSATION_PENDING'
    assert item['verified_success'] is False


def test_projection_recursively_redacts_sensitive_owner_view_fields():
    view=base('recovery_review_required',uncertain=[{'error':{'access_token':'x','safe':'ok'}}])
    view['extra']={'private_key':'pem','nested':[{'client_secret':'y'}]}
    item=ExecutionRecoveryProjection(Authority(view)).detail('tx1')
    assert item['uncertain'][0]['error']['access_token']=='[redacted]'
    assert item['extra']['private_key']=='[redacted]'
    assert item['extra']['nested'][0]['client_secret']=='[redacted]'


def test_missing_transaction_is_safe_none():
    assert ExecutionRecoveryProjection(Authority(base())).detail('missing') is None


def test_projection_cannot_execute_verify_retry_or_compensate():
    projection=ExecutionRecoveryProjection(Authority(base()))
    for name in ('begin_dispatch','record_verification','retry_decision','authorize_compensation','record_compensation_result'):
        assert not hasattr(projection,name)


class BoundAuthority(Authority):
    class Con:
        def __init__(self,binding): self.binding=binding
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def execute(self,sql,args):
            if args[0] != 'tx1': return None
            class Row(dict):
                __getattr__=dict.__getitem__
            return SimpleResult(Row(self.binding))
    def __init__(self,view,binding):
        super().__init__(view); self.binding=binding
    def transaction_binding(self,transaction_id):
        return dict(self.binding) if transaction_id=='tx1' else None


class SimpleResult:
    def __init__(self,row): self.row=row
    def fetchone(self): return self.row


def test_recovery_visibility_requires_exact_canonical_owner_device_session_binding():
    authority=BoundAuthority(base(),{'owner_id':'owner','device_id':'d1','session_id':'s1'})
    projection=ExecutionRecoveryProjection(authority)
    assert projection.detail('tx1',owner_id='owner',device_id='d1',session_id='s1') is not None
    assert projection.detail('tx1',owner_id='other',device_id='d1',session_id='s1') is None
    assert projection.detail('tx1',owner_id='owner',device_id='d2',session_id='s1') is None
    assert projection.detail('tx1',owner_id='owner',device_id='d1',session_id='s2') is None


def test_recovery_visibility_fails_closed_for_partial_or_missing_binding():
    authority=BoundAuthority(base(),{'owner_id':'owner','device_id':'d1','session_id':'s1'})
    projection=ExecutionRecoveryProjection(authority)
    assert projection.detail('tx1',owner_id='owner',device_id='d1',session_id=None) is None
    assert projection.detail('missing',owner_id='owner',device_id='d1',session_id='s1') is None


def test_recovery_api_requires_trusted_active_authorized_exact_session(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.middleware.base import BaseHTTPMiddleware
    from security.request_context import TrustedRequestContext, set_trusted_request, reset_trusted_request
    from server.recovery_visibility_api import recovery_visibility_router

    authority=BoundAuthority(base(),{'owner_id':'owner','device_id':'d1','session_id':'s1'})
    class Devices:
        def __init__(self,active=True,allowed=True): self.active=active; self.allowed=allowed
        def is_active(self,device_id): return self.active and device_id=='d1'
        def authorize(self,device_id,scope): return self.allowed and device_id=='d1' and scope=='ai:chat'
    class Tools:
        def ensure_recovery_authority(self): return authority
    class ContextMiddleware(BaseHTTPMiddleware):
        def __init__(self,app,session='s1'): super().__init__(app); self.session=session
        async def dispatch(self,request,call_next):
            token=set_trusted_request(TrustedRequestContext('d1',self.session))
            try:return await call_next(request)
            finally:reset_trusted_request(token)
    def client(devices,session='s1',trusted=True):
        app=FastAPI()
        if trusted: app.add_middleware(ContextMiddleware,session=session)
        app.include_router(recovery_visibility_router({'device_registry':devices,'tools':Tools()}))
        return TestClient(app)
    assert client(Devices(),trusted=False).get('/iphone/api/execution-recovery/tx1').status_code==401
    assert client(Devices(active=False)).get('/iphone/api/execution-recovery/tx1').status_code==401
    assert client(Devices(allowed=False)).get('/iphone/api/execution-recovery/tx1').status_code==403
    assert client(Devices(),session='other').get('/iphone/api/execution-recovery/tx1').status_code==404
    response=client(Devices()).get('/iphone/api/execution-recovery/tx1')
    assert response.status_code==200 and response.json()['transaction_id']=='tx1'
