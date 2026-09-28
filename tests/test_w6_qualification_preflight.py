from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from qualification.google_connector_preflight import (
    QualificationPreflightError,
    assert_application_routes,
    safe_log,
    validate_qualification_environment,
)


def ready_storage(settings, *, environ=None, mount_points=None):
    assert str(settings.data_dir) == '/data'
    return {'state': 'ready', 'durable': True, 'data_dir': '/data', 'mount_point': '/data'}


def env():
    return {
        'GOOGLE_CLIENT_ID': 'client-id',
        'GOOGLE_CLIENT_SECRET': 'client-secret',
        'PERSONAL_AI_ROOT_KEY': 'root-key',
        'PERSONAL_AI_IPHONE_ENROLLMENT_CODE': 'enroll-code',
        'OAUTH_REDIRECT_URI': 'https://qualification.example/connector-oauth/callback',
        'PERSONAL_AI_DATA_DIR': '/data',
        'PERSONAL_AI_DURABLE_ROOT': '/data',
    }


def test_preflight_accepts_exact_isolated_contract_without_exposing_values():
    result = validate_qualification_environment(environ=env(), storage_validator=ready_storage)
    assert result['ok'] is True
    assert result['callback'] == {'scheme': 'https', 'host': 'qualification.example', 'path': '/connector-oauth/callback'}
    assert result['storage']['durable'] is True
    assert all(result['configured'].values())
    assert 'client-secret' not in str(result)


def test_preflight_fails_closed_on_missing_secret():
    values = env(); values.pop('GOOGLE_CLIENT_SECRET')
    with pytest.raises(QualificationPreflightError, match='GOOGLE_CLIENT_SECRET'):
        validate_qualification_environment(environ=values, storage_validator=ready_storage)


@pytest.mark.parametrize('uri', [
    'http://qualification.example/connector-oauth/callback',
    'https://qualification.example/wrong',
    'https://qualification.example/connector-oauth/callback?code=bad',
])
def test_preflight_rejects_invalid_callback(uri):
    values = env(); values['OAUTH_REDIRECT_URI'] = uri
    with pytest.raises(QualificationPreflightError):
        validate_qualification_environment(environ=values, storage_validator=ready_storage)


def test_preflight_requires_exact_data_root_and_durable_storage():
    values = env(); values['PERSONAL_AI_DATA_DIR'] = '/tmp/personal-ai'
    with pytest.raises(QualificationPreflightError, match='PERSONAL_AI_DATA_DIR=/data'):
        validate_qualification_environment(environ=values, storage_validator=ready_storage)
    values = env()
    with pytest.raises(QualificationPreflightError, match='durability'):
        validate_qualification_environment(
            environ=values,
            storage_validator=lambda *a, **k: {'state': 'local', 'durable': False},
        )


def test_preflight_rejects_insecure_pwa_mode():
    values = env(); values['PERSONAL_AI_IPHONE_ALLOW_INSECURE'] = 'true'
    with pytest.raises(QualificationPreflightError, match='Insecure'):
        validate_qualification_environment(environ=values, storage_validator=ready_storage)


def test_route_probe_requires_health_callback_and_finalize():
    app = FastAPI()
    @app.get('/health')
    def health(): return {'ok': True}
    @app.get('/connector-oauth/callback')
    def callback(): return 'ok'
    @app.post('/iphone/api/connectors/oauth/finalize')
    def finalize(): return {'ok': True}
    assert assert_application_routes(app)['ok'] is True

    broken = FastAPI()
    @broken.get('/health')
    def only_health(): return {'ok': True}
    with pytest.raises(QualificationPreflightError, match='missing required routes'):
        assert_application_routes(broken)


def test_safe_log_redacts_secret_like_fields():
    text = safe_log({
        'event': 'qualification.test',
        'client_secret': 'do-not-store',
        'access_token': 'do-not-store-token',
        'authorization_code': 'do-not-store-code',
        'status': 'ok',
    })
    assert 'do-not-store' not in text
    assert 'qualification.test' in text
    assert '"status":"ok"' in text
