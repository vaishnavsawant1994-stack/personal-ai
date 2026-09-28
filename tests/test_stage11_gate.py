"""Stage 11: the register stays pending, and simulated packets are rejected."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qualification.stage11 import (
    CASES,
    STAGE10_FREEZE,
    Stage11Rejection,
    blank_register,
    render_matrix,
    submit,
)

ROOT = Path(__file__).resolve().parents[1]


def test_stage11_register_is_pending_and_matches_the_catalog():
    register = blank_register()
    on_disk = json.loads((ROOT / "docs" / "stage11_register.json").read_text(encoding="utf-8"))
    assert on_disk == register
    assert register["frozen"] is False
    assert register["production_ready"] is False
    assert register["owner_environment"]["hardware"] == "iphone-only"
    assert register["owner_environment"]["apple_developer_account"] == "absent"
    assert register["stage10_freeze"] == STAGE10_FREEZE
    assert [case["id"] for case in CASES] == [row["id"] for row in register["cases"]]
    assert all(row["status"].startswith("PENDING_") for row in register["cases"])
    assert all(row["actual"] is None for row in register["cases"])
    matrix = (ROOT / "docs" / "STAGE11_MATRIX.md").read_text(encoding="utf-8")
    assert matrix == render_matrix()
    procedures = (ROOT / "docs" / "STAGE11_PROCEDURES.md").read_text(encoding="utf-8")
    contract = (ROOT / "docs" / "STAGE11_CONTRACT.md").read_text(encoding="utf-8")
    assert STAGE10_FREEZE in contract
    for case in CASES:
        assert case["id"] in matrix
        assert case["id"] in procedures
        section = procedures.split(f"## {case['id']}", 1)[1].split("\n## ", 1)[0]
        for heading in ("**Preconditions.**", "**Steps.**", "**Expected result.**", "**Evidence.**", "**Failure handling.**"):
            assert heading in section


def test_stage11_rejects_simulated_and_hosted_passes():
    register = blank_register()
    packet = {
        "case_id": "S11-VOICE-01",
        "verdict": "PASS",
        "evidence_class": "simulated",
        "form": "physical",
        "runner": "owner-mac",
        "source_sha": "a" * 40,
        "captured_at": "2026-09-28T12:00:00+00:00",
        "platform": "mac",
        "os_version": "15",
        "device_id": "mic-1",
        "operation_id": "op-1",
        "expected": "capture",
        "actual": "spoke",
        "audit_ref": "log-1",
    }
    with pytest.raises(Stage11Rejection, match="evidence_class_is_not_physical"):
        submit(register, packet)
    packet["evidence_class"] = "real_device"
    packet["runner"] = "ubuntu-latest"
    with pytest.raises(Stage11Rejection):
        submit(register, packet)
    packet["runner"] = "owner-phone"
    packet["device_id"] = "emulator-5554"
    with pytest.raises(Stage11Rejection, match="not_a_physical_environment"):
        submit(register, packet)
    assert register["cases"][2]["status"] == "PENDING_PHYSICAL"
    assert register["cases"][2]["actual"] is None
    packet["device_id"] = "mic-1"
    packet["actual"] = "simulated"
    with pytest.raises(Stage11Rejection, match="not_a_physical_environment"):
        submit(register, packet)
    packet["actual"] = "spoke"
    packet["device_id"] = "emul\u200bator-1"
    with pytest.raises(Stage11Rejection, match="not_a_physical_environment"):
        submit(register, packet)
    packet["device_id"] = "handset"
    packet["runner"] = "github hosted"
    with pytest.raises(Stage11Rejection, match="not_a_physical_environment"):
        submit(register, packet)
    assert register["cases"][2]["status"] == "PENDING_PHYSICAL"


def test_stage11_emergency_stop_pass_requires_the_owner():
    register = blank_register()
    packet = {
        "case_id": "S11-ESTOP-01",
        "verdict": "PASS",
        "evidence_class": "real_device",
        "form": "physical",
        "runner": "owner-phone",
        "source_sha": "c" * 40,
        "captured_at": "2026-09-28T12:00:00+00:00",
        "platform": "iPhone",
        "os_version": "18",
        "device_id": "iphone-1",
        "operation_id": "op-estop",
        "expected": "stop holds",
        "actual": "stop held",
        "audit_ref": "audit-1",
    }
    with pytest.raises(Stage11Rejection, match="owner_gate_open"):
        submit(register, packet)
    assert register["cases"][4]["status"] == "PENDING_PHYSICAL"


def test_stage11_owner_gate_stays_closed_without_an_owner():
    register = blank_register()
    packet = {
        "case_id": "S11-OAUTH-01",
        "verdict": "PASS",
        "evidence_class": "real_device",
        "form": "physical",
        "runner": "owner-laptop",
        "source_sha": "b" * 40,
        "captured_at": "2026-09-28T12:00:00+00:00",
        "platform": "google",
        "os_version": "account",
        "device_id": "owner-subject",
        "operation_id": "op-oauth",
        "expected": "revoke fails closed",
        "actual": "not run",
        "audit_ref": "none-yet",
    }
    with pytest.raises(Stage11Rejection, match="owner_gate_open"):
        submit(register, packet)
    assert register["cases"][3]["status"] == "PENDING_OWNER"
