from __future__ import annotations

from pathlib import Path


def test_tmp_should_not_create_absent_from_tree():
    root=Path(__file__).resolve().parents[1]
    assert not any(p.name=='tmp_should_not_create' for p in root.rglob('*'))


def test_w76_does_not_redesign_home_or_core():
    root=Path(__file__).resolve().parents[1]
    # This release gate is intentionally source-bound: W7.6 recovery belongs under
    # recovery/tools/settings and must not add a second Home/Core implementation.
    changed_contract=(root/'recovery'/'operator_recovery.py').read_text(encoding='utf-8')+(root/'recovery'/'cross_operator.py').read_text(encoding='utf-8')
    assert 'Home V1' not in changed_contract
    assert 'AI Core redesign' not in changed_contract


def test_recovery_is_not_a_parallel_executor():
    root=Path(__file__).resolve().parents[1]
    text=(root/'recovery'/'cross_operator.py').read_text(encoding='utf-8')
    assert 'operator.execute' in text
    for forbidden in ('subprocess.run','os.system','shell=True','powershell','cmd.exe'):
        assert forbidden not in text


def test_recovery_contract_never_claims_handler_success_is_verification():
    root=Path(__file__).resolve().parents[1]
    text=(root/'recovery'/'operator_recovery.py').read_text(encoding='utf-8')
    assert 'operator_verification_attempts' in text
    assert 'evidence_checksum' in text
    assert 'verified_no_effect' in text
    assert 'unknown_outcome' in text
