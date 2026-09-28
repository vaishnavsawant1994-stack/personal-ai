from __future__ import annotations

import sqlite3

from security.action_audit import REDACTED, TrustedActionAudit


def test_trusted_action_audit_redacts_sensitive_values(tmp_path):
    audit = TrustedActionAudit(tmp_path / 'trusted-action-audit.sqlite3')
    audit.append('tool', 'execute', {
        'recipient': 'person@example.com',
        'authorization': 'Bearer abc123',
        'nested': {'api_key': 'secret-value', 'safe': 'visible'},
        'cookie': 'session=value',
    })

    payload = audit.entries(1)[0]['payload']
    assert payload['recipient'] == 'person@example.com'
    assert payload['authorization'] == REDACTED
    assert payload['nested']['api_key'] == REDACTED
    assert payload['nested']['safe'] == 'visible'
    assert payload['cookie'] == REDACTED
    assert audit.verify_chain()['ok'] is True


def test_trusted_action_audit_detects_row_tampering(tmp_path):
    path = tmp_path / 'trusted-action-audit.sqlite3'
    audit = TrustedActionAudit(path)
    audit.append('approval', 'required', {'tool': 'send'})
    audit.append('approval', 'approved', {'tool': 'send'})

    with sqlite3.connect(path) as con:
        con.execute("UPDATE action_audit SET action='forged' WHERE sequence=1")

    result = audit.verify_chain()
    assert result['ok'] is False
    assert result['reason'] == 'entry hash mismatch'


def test_trusted_action_audit_detects_tail_deletion_via_anchor(tmp_path):
    path = tmp_path / 'trusted-action-audit.sqlite3'
    audit = TrustedActionAudit(path)
    audit.append('tool', 'one', {'ok': True})
    audit.append('tool', 'two', {'ok': True})

    with sqlite3.connect(path) as con:
        con.execute('DELETE FROM action_audit WHERE sequence=2')

    result = audit.verify_chain()
    assert result['ok'] is False
    assert result['reason'] == 'audit anchor mismatch'


def test_trusted_action_audit_redacts_session_identity_without_destroying_public_ids(tmp_path):
    audit = TrustedActionAudit(tmp_path / 'trusted-action-audit.sqlite3')
    audit.append('approval', 'approved', {
        'session_id': 'session-secret-123',
        'device_id': 'device-public-123',
        'request_id': 'request-public-123',
        'execution_id': 'execution-public-123',
    })

    payload = audit.entries(1)[0]['payload']
    assert payload['session_id'] == REDACTED
    assert payload['device_id'] == 'device-public-123'
    assert payload['request_id'] == 'request-public-123'
    assert payload['execution_id'] == 'execution-public-123'
    assert audit.verify_chain()['ok'] is True


def test_trusted_action_audit_redacts_embedded_credentials_in_untrusted_text(tmp_path):
    audit = TrustedActionAudit(tmp_path / 'trusted-action-audit.sqlite3')
    secrets = {
        'bearer': 'audit-bearer-secret-123456',
        'api': 'audit-api-secret-234567',
        'access': 'audit-access-secret-345678',
        'refresh': 'audit-refresh-secret-456789',
        'cookie': 'audit-cookie-secret-567890',
        'password': 'audit-password-secret-678901',
        'pem': 'AUDIT-PRIVATE-BODY-789012',
    }
    hostile = (
        f"provider failed Authorization: Bearer {secrets['bearer']} "
        f"api_key={secrets['api']} access_token={secrets['access']} "
        f"refresh_token={secrets['refresh']} Cookie: sid={secrets['cookie']}; Path=/ "
        f"password={secrets['password']} "
        f"https://provider.invalid/callback?token={secrets['access']}&safe=1 "
        f"-----BEGIN PRIVATE KEY-----\n{secrets['pem']}\n-----END PRIVATE KEY-----"
    )
    audit.append('provider', 'failed', {'message': hostile, 'nested': {'tool_error': hostile}})
    payload = audit.entries(1)[0]['payload']
    rendered = str(payload)
    for secret in secrets.values():
        assert secret not in rendered
    assert audit.verify_chain()['ok'] is True


def test_trusted_action_audit_redaction_preserves_legitimate_public_identifiers(tmp_path):
    audit = TrustedActionAudit(tmp_path / 'trusted-action-audit.sqlite3')
    values = {
        'device_id': 'device-public-123',
        'request_id': '550e8400-e29b-41d4-a716-446655440000',
        'activity_id': 'activity-public-456',
        'conversation_id': 'conversation-public-789',
        'public_url': 'https://example.test/public/path?safe=1',
        'owner_text': 'The token budget is 1000 and Press the key marked Enter.',
    }
    audit.append('runtime', 'visible', values)
    payload = audit.entries(1)[0]['payload']
    assert payload == values
    assert audit.verify_chain()['ok'] is True
