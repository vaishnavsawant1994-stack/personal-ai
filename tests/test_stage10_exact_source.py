"""Stage 10: the Python lock matches the entry ranges, and a clean data dir needs no manual repair."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from types import SimpleNamespace

from cloud_runtime.security import CloudSessionStore
from devices.continuity import ContinuityService
from devices.registry import DeviceRegistry
from knowledge.store import KnowledgeStore
from security.approvals import ApprovalManager
from security.pwa_sessions import PwaSessionStore
from tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_SHA256 = "24c0a234837bdc15b82e14263905337dc8ec857ee095570046873ea2869bd4fb"


def _names(text: str) -> set[str]:
    found = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name = re.split(r"[<>=\[]", line, maxsplit=1)[0].strip()
        found.add(name.lower().replace("_", "-"))
    return found


def test_stage10_requirements_bytes_match_the_entry_contract():
    raw = (ROOT / "requirements.txt").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REQUIREMENTS_SHA256
    contract = (ROOT / "docs" / "STAGE10_CONTRACT.md").read_text(encoding="utf-8")
    assert REQUIREMENTS_SHA256 in contract
    assert "ddd53d17d60db2e5e5438cf29e2d704a9ba69af0" in contract


def test_stage10_lock_covers_every_direct_requirement():
    direct = _names((ROOT / "requirements.txt").read_text(encoding="utf-8"))
    locked = _names((ROOT / "requirements-3.12.lock").read_text(encoding="utf-8"))
    assert direct <= locked
    assert "fastapi" in locked
    assert "pyqt6" in locked


def test_stage10_clean_data_directory_restarts_without_manual_repair(tmp_path: Path):
    settings = SimpleNamespace(autonomy_mode="ask", data_dir=tmp_path)
    ToolRegistry(settings).set_emergency_stop(True)
    DeviceRegistry(tmp_path / "devices.sqlite3")
    KnowledgeStore(tmp_path / "knowledge.sqlite3", tmp_path / "objects")
    ContinuityService(tmp_path / "continuity.sqlite3")
    ApprovalManager(path=tmp_path / "trusted-actions.sqlite3")
    CloudSessionStore(tmp_path / "cloud-sessions.sqlite3", ttl_seconds=60)
    PwaSessionStore(tmp_path / "pwa-sessions.sqlite3")

    restarted = ToolRegistry(settings)
    assert restarted.emergency_stop is True
    assert DeviceRegistry(tmp_path / "devices.sqlite3").list() == []
    assert KnowledgeStore(tmp_path / "knowledge.sqlite3", tmp_path / "objects") is not None
    assert ContinuityService(tmp_path / "continuity.sqlite3") is not None
    assert ApprovalManager(path=tmp_path / "trusted-actions.sqlite3").current_security_epoch() >= 0
    token, session = CloudSessionStore(tmp_path / "cloud-sessions.sqlite3", ttl_seconds=60).issue("dev-clean")
    assert token and session.device_id == "dev-clean"
    assert PwaSessionStore(tmp_path / "pwa-sessions.sqlite3").active_for_device("missing") == []
