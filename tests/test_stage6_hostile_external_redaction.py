from copy import deepcopy

from activities.projection import ActivitiesProjection
from approvals.projection import ApprovalsProjection
from automation.projection import AutomationWorkflowProjection
from recovery.visibility_projection import ExecutionRecoveryProjection
from security.approvals import ApprovalManager
from security.projection_redaction import sanitize_sensitive_text

SECRET_BEARER='stage6-secret-bearer-123456'
SECRET_API='stage6-api-secret-234567'
SECRET_COOKIE='stage6-cookie-secret-345678'
SECRET_QUERY='stage6-query-secret-456789'
SECRET_PASSWORD='stage6-password-secret-567890'
SECRET_PEM='STAGE6-PRIVATE-BODY-678901'
OWNER_CONTROL='ordinary-owner-reference-654321'
HOSTILE=(f'Authorization: Bearer {SECRET_BEARER} api_key={SECRET_API} '
         f'Cookie: session={SECRET_COOKIE}; path=/ '
         f'https://provider.invalid/path?access_token={SECRET_QUERY}&safe=1 '
         f'password={SECRET_PASSWORD} -----BEGIN PRIVATE KEY-----\\n{SECRET_PEM}\\n-----END PRIVATE KEY-----')
SECRETS=(SECRET_BEARER,SECRET_API,SECRET_COOKIE,SECRET_QUERY,SECRET_PASSWORD,SECRET_PEM)


def assert_clean(value):
    text=str(value)
    for secret in SECRETS: assert secret not in text


def test_sensitive_value_redaction_preserves_normal_owner_text():
    normal=f'Owner note: project reference {OWNER_CONTROL}; the word token is ordinary here.'
    assert sanitize_sensitive_text(normal)==normal
    assert OWNER_CONTROL in sanitize_sensitive_text(normal)
    assert_clean(sanitize_sensitive_text(HOSTILE))


def test_false_negative_matrix_and_idempotency():
    variants=[
        f'Authorization: Bearer {SECRET_BEARER}', f'authorization:\t bearer {SECRET_BEARER}',
        f'Authorization: Basic {SECRET_BEARER}', f'AUTHORIZATION:\tBASIC   {SECRET_BEARER}',
        f'Bearer {SECRET_BEARER}', f'bearer {SECRET_BEARER}', f'api_key={SECRET_API}',
        f'api-key={SECRET_API}', f'apikey={SECRET_API}', f'API_KEY="{SECRET_API}"',
        f'access_token={SECRET_QUERY}', f'refresh_token={SECRET_QUERY}', f'session_token={SECRET_QUERY}',
        f'session_secret={SECRET_QUERY}', f'password={SECRET_PASSWORD}', f'passwd={SECRET_PASSWORD}',
        f'Cookie: auth={SECRET_COOKIE}', f'Set-Cookie: session={SECRET_COOKIE}; HttpOnly',
        f'https://x.invalid/?token={SECRET_QUERY}&safe=1', f'https://x.invalid/?access_token={SECRET_QUERY}',
        f'https://x.invalid/?api_key={SECRET_API}', f'-----BEGIN PRIVATE KEY-----\\n{SECRET_PEM}\\n-----END PRIVATE KEY-----',
    ]
    for value in variants:
        clean=sanitize_sensitive_text(value); assert_clean(clean); assert sanitize_sensitive_text(clean)==clean


def test_false_positive_matrix_preserves_noncredential_data():
    safe=[OWNER_CONTROL,'550e8400-e29b-41d4-a716-446655440000','request_id=req-public-123',
          'https://example.test/public/path?safe=1','The token budget is 1000.','Press the key marked Enter.',
          'Public key terminology is allowed.','Company API Keynote Conference']
    for value in safe: assert sanitize_sensitive_text(value)==value


def test_activities_redact_hostile_ordinary_external_fields_without_mutating_source():
    source={'message':HOSTILE,'detail':{'description':HOSTILE},'owner_note':f'Owner reference {OWNER_CONTROL}'}
    before=deepcopy(source); entry={'id':'a','category':'tool','action':'failed','created_at':'now','payload':source}
    projected=ActivitiesProjection.project_entry(entry); assert_clean(projected); assert source==before
    assert OWNER_CONTROL in projected['details']['owner_note']


def test_approval_outcome_and_destination_use_real_approval_contract(tmp_path):
    manager=ApprovalManager(path=tmp_path/'approvals.sqlite3')
    ticket=manager.create('e','t',{},owner_id='owner',device_id='d',session_id='s',destination=f'https://x.invalid/?access_token={SECRET_QUERY}')
    manager.approve(ticket.id,'e','t',{},owner_id='owner',device_id='d',session_id='s'); manager.begin_dispatch(ticket.id)
    manager.complete_dispatch(ticket.id,{'message':HOSTILE})
    item=ApprovalsProjection(manager).detail(ticket.id,owner_id='owner',device_id='d',session_id='s'); assert_clean(item)


def test_automation_safe_value_redacts_hostile_nested_text():
    assert_clean(AutomationWorkflowProjection._safe({'result':{'message':HOSTILE},'status_text':HOSTILE}))


def test_recovery_safe_value_redacts_hostile_nested_text():
    assert_clean(ExecutionRecoveryProjection._safe({'error':{'message':HOSTILE},'evidence':[{'detail':HOSTILE}]}))


def test_large_hostile_string_is_bounded_by_projection_before_exposure():
    value=('safe-prefix '*1000)+HOSTILE
    projected=ActivitiesProjection.project_entry({'id':'a','category':'tool','action':'failed','created_at':'now','payload':{'message':value}})
    assert len(projected['details']['message'])<=1000


def test_basic_authorization_redaction_covers_nested_projection_and_audit_paths(tmp_path):
    variants=[
        f'Authorization: Basic {SECRET_BEARER}',
        f'authorization: basic {SECRET_BEARER}',
        f'AUTHORIZATION:\tBASIC   {SECRET_BEARER}',
    ]
    audit=__import__('security.action_audit',fromlist=['TrustedActionAudit']).TrustedActionAudit(tmp_path/'audit.sqlite3')
    for value in variants:
        clean=sanitize_sensitive_text(value)
        assert SECRET_BEARER not in clean
        assert sanitize_sensitive_text(clean)==clean
        nested={'error':{'message':value},'detail':[{'provider_error':value}]}
        assert_clean(AutomationWorkflowProjection._safe(nested))
        assert_clean(ExecutionRecoveryProjection._safe(nested))
        projected=ActivitiesProjection.project_entry({'id':'basic','category':'provider','action':'failed','created_at':'now','payload':nested})
        assert_clean(projected)
        audit.append('provider','failed',nested)
    assert_clean(audit.entries(10))
    assert audit.verify_chain()['ok'] is True
