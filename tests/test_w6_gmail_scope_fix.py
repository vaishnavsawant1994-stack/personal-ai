from types import SimpleNamespace
import pytest

from integrations.contracts import gmail_manifest, calendar_manifest, drive_manifest, sheets_manifest
from integrations.gateway import ConnectorError, ConnectorGateway
from integrations.oauth import OAuthAccountManager
from integrations.runtime import _runtime_manifest, provider_catalog
from qualification.google_connectors import GoogleQualificationEvidence, GoogleQualificationRecorder

COMPOSE='https://www.googleapis.com/auth/gmail.compose'
READ='https://www.googleapis.com/auth/gmail.readonly'
SEND='https://www.googleapis.com/auth/gmail.send'
MODIFY='https://www.googleapis.com/auth/gmail.modify'
MAIL_FULL='https://mail.google.com/'


def test_runtime_gmail_manifest_exposes_compose_without_full_access():
    raw=gmail_manifest(); live=_runtime_manifest(raw)
    assert raw.operation('gmail.draft').required_scopes == (COMPOSE,)
    assert COMPOSE in live.optional_oauth_scopes
    assert MAIL_FULL not in live.optional_oauth_scopes
    assert live.required_oauth_scopes == (READ,)


def test_gmail_draft_scope_rejected_without_compose_and_permitted_with_it():
    operation=gmail_manifest().operation('gmail.draft')
    adapter=SimpleNamespace(granted_scopes={READ,SEND,MODIFY})
    with pytest.raises(ConnectorError,match='required permission scope') as exc:
        ConnectorGateway._scope_check(adapter,operation)
    assert exc.value.code == 'insufficient_scope'
    adapter.granted_scopes.add(COMPOSE)
    ConnectorGateway._scope_check(adapter,operation)


def test_read_search_and_send_scope_contracts_are_unchanged():
    manifest=gmail_manifest()
    assert manifest.operation('gmail.read').required_scopes == (READ,)
    assert manifest.operation('gmail.search').required_scopes == (READ,)
    assert manifest.operation('gmail.send').required_scopes == (SEND,)


def test_google_provider_catalog_preserves_connector_scope_union():
    settings=SimpleNamespace(google_client_id='client',google_client_secret='secret',slack_client_id='')
    scopes=set(provider_catalog(settings)['google'].scopes)
    expected={READ,COMPOSE,SEND,MODIFY}
    expected.update(calendar_manifest().required_oauth_scopes); expected.update(calendar_manifest().optional_oauth_scopes)
    expected.update(drive_manifest().required_oauth_scopes); expected.update(drive_manifest().optional_oauth_scopes)
    expected.update(sheets_manifest().required_oauth_scopes); expected.update(sheets_manifest().optional_oauth_scopes)
    assert expected <= scopes
    assert MAIL_FULL not in scopes


def test_google_scope_union_preserved_and_reduced_scope_detected():
    previous={'granted_scopes':[READ,SEND],'confirmed_granted_scopes':[READ,SEND]}
    expanded=OAuthAccountManager._scope_record(previous,{'scope':f'{READ} {SEND} {COMPOSE}'},[COMPOSE])
    assert set(expanded['confirmed_granted_scopes']) == {READ,SEND,COMPOSE}
    assert expanded['scope_reduction_detected'] is False
    reduced=OAuthAccountManager._scope_record(expanded,{'scope':COMPOSE},[COMPOSE])
    assert reduced['scope_reduction_detected'] is True
    assert set(reduced['reduced_scopes']) == {READ,SEND}
    assert set(reduced['confirmed_granted_scopes']) == {READ,SEND,COMPOSE}


def test_gmail_scope_evidence_remains_redacted(tmp_path):
    recorder=GoogleQualificationRecorder(tmp_path/'gmail-scope-evidence.jsonl')
    recorder.append(GoogleQualificationEvidence(
        git_sha='candidate',deployment_id='local',environment='test',service='unit',
        google_account='qualification@example.com',connector='gmail',granted_scopes=[READ,COMPOSE,SEND],
        owner_id='owner',device_id='device',session_id='session',security_epoch=1,operation_id='scope-check',
        expected_result='compose granted',actual_result='compose granted',timestamp=1.0,
        safe_logs={'access_token':'never-store','authorization_code':'never-store-code','scope_count':3},
        artifact_ref='local:test',passed=True,evidence_kind='simulated_provider'))
    text=(tmp_path/'gmail-scope-evidence.jsonl').read_text()
    assert 'qualification@example.com' not in text
    assert 'never-store' not in text
    assert 'never-store-code' not in text
    assert COMPOSE in text
