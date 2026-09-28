from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from core.storage import StorageUnavailable, validate_runtime_storage

CALLBACK_PATH = '/connector-oauth/callback'
FINALIZE_PATH = '/iphone/api/connectors/oauth/finalize'
HEALTH_PATH = '/health'
REQUIRED_SECRET_NAMES = (
    'GOOGLE_CLIENT_ID',
    'GOOGLE_CLIENT_SECRET',
    'PERSONAL_AI_ROOT_KEY',
    'PERSONAL_AI_IPHONE_ENROLLMENT_CODE',
)
REQUIRED_VALUE_NAMES = (
    'OAUTH_REDIRECT_URI',
    'PERSONAL_AI_DATA_DIR',
    'PERSONAL_AI_DURABLE_ROOT',
)


class QualificationPreflightError(RuntimeError):
    pass


def _present(env, name: str) -> bool:
    return bool(str(env.get(name, '')).strip())


def _callback(value: str) -> dict:
    parsed = urlparse(str(value or '').strip())
    if parsed.scheme != 'https' or not parsed.hostname:
        raise QualificationPreflightError('OAUTH_REDIRECT_URI must be an absolute HTTPS URL')
    if parsed.path != CALLBACK_PATH or parsed.params or parsed.query or parsed.fragment:
        raise QualificationPreflightError(f'OAUTH_REDIRECT_URI must end exactly with {CALLBACK_PATH}')
    return {'scheme': parsed.scheme, 'host': parsed.hostname, 'path': parsed.path}


def validate_qualification_environment(*, environ=None, mount_points=None, require_secrets=True, storage_validator=None) -> dict:
    env = dict(os.environ if environ is None else environ)
    missing = [name for name in REQUIRED_VALUE_NAMES if not _present(env, name)]
    if require_secrets:
        missing.extend(name for name in REQUIRED_SECRET_NAMES if not _present(env, name))
    if missing:
        raise QualificationPreflightError('Missing required qualification variables: ' + ', '.join(sorted(set(missing))))

    data_dir = Path(env['PERSONAL_AI_DATA_DIR']).expanduser().resolve()
    durable_root = Path(env['PERSONAL_AI_DURABLE_ROOT']).expanduser().resolve()
    if data_dir != Path('/data'):
        raise QualificationPreflightError('Qualification service requires PERSONAL_AI_DATA_DIR=/data')
    if durable_root != Path('/data'):
        raise QualificationPreflightError('Qualification service requires PERSONAL_AI_DURABLE_ROOT=/data')

    callback = _callback(env['OAUTH_REDIRECT_URI'])
    if env.get('PERSONAL_AI_IPHONE_ALLOW_INSECURE', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        raise QualificationPreflightError('Insecure iPhone/PWA mode must remain disabled for connector qualification')

    settings = SimpleNamespace(data_dir=data_dir, hosted_runtime=True, cloud_runtime_enabled=False)
    validator = storage_validator or validate_runtime_storage
    try:
        storage = validator(settings, environ=env, mount_points=mount_points)
    except StorageUnavailable as exc:
        raise QualificationPreflightError(str(exc)) from exc
    if storage.get('state') != 'ready' or not storage.get('durable'):
        raise QualificationPreflightError('Qualification storage durability could not be proven')

    return {
        'ok': True,
        'service_role': 'google_connector_qualification',
        'callback': callback,
        'health_path': HEALTH_PATH,
        'finalize_path': FINALIZE_PATH,
        'storage': {
            'state': storage.get('state'),
            'data_dir': storage.get('data_dir'),
            'mount_point': storage.get('mount_point'),
            'durable': bool(storage.get('durable')),
        },
        'configured': {name: _present(env, name) for name in (*REQUIRED_SECRET_NAMES, *REQUIRED_VALUE_NAMES)},
    }


def assert_application_routes(app) -> dict:
    paths = {getattr(route, 'path', '') for route in getattr(app, 'routes', [])}
    required = {HEALTH_PATH, CALLBACK_PATH, FINALIZE_PATH}
    missing = sorted(required - paths)
    if missing:
        raise QualificationPreflightError('Qualification application is missing required routes: ' + ', '.join(missing))
    return {'ok': True, 'required_routes': sorted(required)}


def safe_log(record: dict) -> str:
    safe = dict(record or {})
    for key in list(safe):
        low = str(key).lower()
        if any(word in low for word in ('secret', 'token', 'authorization_code', 'verifier', 'password', 'content')):
            safe[key] = '[REDACTED]'
    return json.dumps(safe, sort_keys=True, separators=(',', ':'))


def main() -> int:
    try:
        result = validate_qualification_environment()
    except QualificationPreflightError as exc:
        print(safe_log({'event': 'qualification.preflight.failed', 'error': str(exc)}), flush=True)
        return 2
    print(safe_log({'event': 'qualification.preflight.ready', **result}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
