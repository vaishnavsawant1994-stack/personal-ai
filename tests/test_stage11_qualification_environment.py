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
