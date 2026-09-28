"""The Stage 11 qualification process names one SHA and passes no row."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qualification.stage11_environment import qualification_process
from qualification.stage11_identity import RECOVERY_CHECKPOINT, public_identity

ROOT = Path(__file__).resolve().parents[1]


def test_identity_is_absent_unless_this_process_is_the_qualification_runtime(monkeypatch):
    monkeypatch.delenv('PERSONAL_AI_ENVIRONMENT', raising=False)
    monkeypatch.delenv('PERSONAL_AI_SOURCE_SHA', raising=False)
    monkeypatch.delenv('PERSONAL_AI_PRODUCTION', raising=False)
    body, code = public_identity()
    assert code == 404
    assert body['source_sha'] is None
    assert body['rows_passed'] == 0
    assert body['stage11_freeze'] is False


def test_identity_refuses_production_and_a_movable_sha(monkeypatch):
    monkeypatch.setenv('PERSONAL_AI_ENVIRONMENT', 'production')
    monkeypatch.setenv('PERSONAL_AI_SOURCE_SHA', 'b' * 40)
    body, code = public_identity()
    assert code == 404
    assert body['error'] == 'production_is_not_a_stage11_environment'
    monkeypatch.setenv('PERSONAL_AI_ENVIRONMENT', 'stage11-qualification')
    monkeypatch.setenv('PERSONAL_AI_SOURCE_SHA', 'latest')
    body, code = public_identity()
    assert code == 503
    assert body['error'] == 'source_sha_not_exact'
    assert body['rows_passed'] == 0


def test_identity_names_the_exact_candidate_without_passing_a_row(monkeypatch):
    sha = 'c' * 40
    monkeypatch.setenv('PERSONAL_AI_ENVIRONMENT', 'stage11-qualification')
    monkeypatch.setenv('PERSONAL_AI_PRODUCTION', 'false')
    monkeypatch.setenv('PERSONAL_AI_SOURCE_SHA', sha)
    body, code = public_identity()
    assert code == 200
    assert body['source_sha'] == sha
    assert body['environment'] == 'stage11-qualification'
    assert body['production'] is False
    assert body['candidate_only'] is True
    assert body['public_p2_is_this_environment'] is False
    assert body['recovery_checkpoint'] == RECOVERY_CHECKPOINT
    assert body['rows_passed'] == 0
    assert body['stage12_open'] is False


def test_process_refuses_the_public_site_and_the_default_data_dir(tmp_path):
    with pytest.raises(ValueError, match='refusing_production_host'):
        qualification_process(source_sha='d' * 40, data_dir=tmp_path, host='personal-ai-runtime-production.up.railway.app')
    with pytest.raises(ValueError, match='refusing_default_owner_data_dir'):
        qualification_process(source_sha='d' * 40, data_dir=Path.home() / '.personal_ai', host='127.0.0.1')
    env = qualification_process(source_sha='d' * 40, data_dir=tmp_path, host='127.0.0.1')
    assert env['PERSONAL_AI_ENVIRONMENT'] == 'stage11-qualification'
    assert env['PERSONAL_AI_PRODUCTION'] == 'false'
    assert env['PERSONAL_AI_SOURCE_SHA'] == 'd' * 40


def test_identity_is_readable_before_sign_in():
    from server.pwa_session_middleware import PUBLIC_PATHS
    assert '/iphone/api/stage11/identity' in PUBLIC_PATHS
    register = json.loads((ROOT / 'docs' / 'stage11_register.json').read_text(encoding='utf-8'))
    assert register['frozen'] is False
    assert register['production_ready'] is False
    assert all(row['actual'] is None and row['source_sha'] is None for row in register['cases'])
    text = (ROOT / 'server' / 'iphone_pwa.py').read_text(encoding='utf-8')
    assert "/api/stage11/identity" in text


def test_durability_requires_a_real_mount_and_stays_non_production():
    from qualification.stage11_environment import qualification_durability
    mounted = qualification_durability(Path('/data/stage11/owner'), Path('/data'), [Path('/data')])
    assert mounted['durable'] is True
    assert mounted['mount_point'] == '/data'
    ephemeral = qualification_durability(Path('/tmp/stage11'), Path('/tmp'), [Path('/tmp')])
    assert ephemeral['durable'] is False
    missing = qualification_durability(Path('/data/stage11/owner'), Path('/data'), [Path('/')])
    assert missing['reason'] == 'no_durable_mount'
    private_tmp = qualification_durability(Path('/private/tmp/stage11'), Path('/private/tmp'), [Path('/private/tmp')])
    assert private_tmp['durable'] is False
    with pytest.raises(ValueError, match='refusing_production_host'):
        qualification_process(source_sha='d' * 40, data_dir=Path('/data/stage11/owner'), host='personal-ai-runtime-production.up.railway.app:443')
    from qualification.stage11_environment import stable_endpoint
    assert stable_endpoint({'PERSONAL_AI_QUALIFICATION_PUBLIC_HOST': 'personal-ai-runtime-production.up.railway.app.'}) is False
    with pytest.raises(ValueError, match='refusing_unqualified_host'):
        qualification_process(source_sha='d' * 40, data_dir=Path('/data/stage11/owner'), host='name.trycloudflare.com')


def test_identity_is_not_ready_for_a_physical_pass_without_every_gate(monkeypatch):
    monkeypatch.setenv('PERSONAL_AI_ENVIRONMENT', 'stage11-qualification')
    monkeypatch.setenv('PERSONAL_AI_PRODUCTION', 'false')
    monkeypatch.setenv('PERSONAL_AI_SOURCE_SHA', 'e' * 40)
    monkeypatch.setenv('PERSONAL_AI_DATA_DIR', '/data/stage11/owner')
    monkeypatch.setenv('PERSONAL_AI_QUALIFICATION_DURABLE_ROOT', '/data')
    for name in ('GEMINI_API_KEY', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'SELF_HOSTED_AI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PERSONAL_AI_QUALIFICATION_PUBLIC_HOST', 'name.trycloudflare.com')
    body, code = public_identity()
    assert code == 200
    assert body['production'] is False
    assert body['ready_for_physical'] is False
    assert body['rows_passed'] == 0
    monkeypatch.setenv('GEMINI_API_KEY', 'not-for-git')
    monkeypatch.setenv('PERSONAL_AI_QUALIFICATION_PUBLIC_HOST', 'stage11.example.test')
    monkeypatch.setattr(
        'qualification.stage11_environment.durability_from_environ',
        lambda environ=None, mount_points=None: {'durable': True, 'reason': 'mounted', 'mount_point': '/data'},
    )
    body, code = public_identity()
    assert 'not-for-git' not in json.dumps(body)
    assert body['model_configured'] is True
    assert body['stable_endpoint'] is True
    assert body['durable'] is True
    assert body['ready_for_physical'] is True
    assert body['rows_passed'] == 0
    assert body['stage11_freeze'] is False
