"""Stage 11 physical-evidence gate.

Opening a register records every case as pending. A simulated, emulated,
or GitHub-hosted packet cannot change that. This module does not talk to
a device and it does not invent a pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

STAGE10_FREEZE = "cd558936276aece705fa46032e3bab6453c7f014"
STAGE8_FREEZE = "b17c5051772b5e82b7a6a208903bb0300bf1e405"
STAGE9_FREEZE = "ddd53d17d60db2e5e5438cf29e2d704a9ba69af0"

_SHA = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN = (
    "qemu",
    "emulator",
    "simulator",
    "sdk_gphone",
    "goldfish",
    "ranchu",
    "github-hosted",
    "hostedtoolcache",
    "ubuntu-latest",
    "macos-latest",
    "windows-latest",
)
_HOSTED_RUNNERS = {"ubuntu-latest", "macos-latest", "windows-latest", "github-hosted"}


class Stage11Rejection(ValueError):
    """The packet is not physical evidence and must not change the register."""


CASES: tuple[dict[str, str], ...] = (
    {
        "id": "S11-IOS-01",
        "title": "iPhone trusted-device journey",
        "status": "PENDING_PHYSICAL+PENDING_OWNER",
        "expected": "Authenticate, establish a trusted device, use Conversation and Memory/Knowledge, use a connector, revoke the device, and prove access fails.",
    },
    {
        "id": "S11-ANDROID-01",
        "title": "Android trusted-device journey",
        "status": "PENDING_PHYSICAL+PENDING_OWNER",
        "expected": "Authenticate, grant permissions, keep a session, hand off continuity, revoke the device, and prove the stale session cannot continue.",
    },
    {
        "id": "S11-VOICE-01",
        "title": "Physical microphone journey",
        "status": "PENDING_PHYSICAL",
        "expected": "Capture from a physical microphone, honor permission, process, call the model, speak a response, cancel on interruption, and honor Emergency Stop.",
    },
    {
        "id": "S11-OAUTH-01",
        "title": "Real provider login",
        "status": "PENDING_OWNER",
        "expected": "Complete a real provider login and callback, store the token, perform one permitted operation, revoke the provider, and prove the stale credential fails closed.",
    },
    {
        "id": "S11-ESTOP-01",
        "title": "Live Emergency Stop cycle",
        "status": "PENDING_PHYSICAL",
        "expected": "Start a real activity, activate Emergency Stop, block new work, block queued or retried work, restart, confirm it stays stopped, then reset only with an explicit authorization and confirm execution returns.",
    },
    {
        "id": "S11-FAIL-01",
        "title": "Network disappears during execution",
        "status": "PENDING_PHYSICAL",
        "expected": "Drop the network during a real operation and record whether the operation fails closed and what is retried after reconnect.",
    },
    {
        "id": "S11-FAIL-02",
        "title": "App backgrounded or killed",
        "status": "PENDING_PHYSICAL",
        "expected": "Background or kill the app during a real operation and record the recovered state. No silent success.",
    },
    {
        "id": "S11-FAIL-03",
        "title": "Phone reconnects",
        "status": "PENDING_PHYSICAL",
        "expected": "Reconnect a real phone after a drop and record whether the session resumes or fails closed.",
    },
    {
        "id": "S11-FAIL-04",
        "title": "Stale session reused",
        "status": "PENDING_PHYSICAL",
        "expected": "Reuse a stale device session and prove it is rejected.",
    },
    {
        "id": "S11-FAIL-05",
        "title": "Device revoked while active",
        "status": "PENDING_PHYSICAL",
        "expected": "Revoke a device during an active real session and prove later calls fail.",
    },
    {
        "id": "S11-FAIL-06",
        "title": "Provider credential revoked externally",
        "status": "PENDING_OWNER",
        "expected": "Revoke the provider credential outside Personal AI and prove the next call fails closed.",
    },
    {
        "id": "S11-FAIL-07",
        "title": "Microphone permission denied or revoked",
        "status": "PENDING_PHYSICAL",
        "expected": "Deny or revoke microphone permission on a real device and prove capture does not proceed.",
    },
    {
        "id": "S11-FAIL-08",
        "title": "Server restarted while stopped",
        "status": "PENDING_PHYSICAL+PENDING_OWNER",
        "expected": "Restart the owner server while Emergency Stop is on and prove the stop is still on after restart.",
    },
    {
        "id": "S11-FAIL-09",
        "title": "Two-device handoff",
        "status": "PENDING_PHYSICAL+PENDING_OWNER",
        "expected": "Hand off between two real devices and record which session survives. A revoked device must not continue.",
    },
    {
        "id": "S11-FAIL-10",
        "title": "Emergency Stop during an operation",
        "status": "PENDING_PHYSICAL",
        "expected": "Activate Emergency Stop while a real operation is in progress and prove it does not finish as success.",
    },
)


def blank_register() -> dict:
    return {
        "stage": 11,
        "frozen": False,
        "stage8_freeze": STAGE8_FREEZE,
        "stage9_freeze": STAGE9_FREEZE,
        "stage10_freeze": STAGE10_FREEZE,
        "production_ready": False,
        "owner_environment": {
            "recorded": "2026-09-28",
            "hardware": "iphone-only",
            "apple_developer_account": "absent",
            "statement": "Owner has a physical iPhone and no Apple Developer account. No laptop or Android phone was reported. No Stage 11 session was run.",
            "effect": "Native iOS install stays blocked on signing. The Safari PWA does not need that account, but no phone session was captured. Every row stays pending. This is not a pass or a Stage 11 freeze.",
        },
        "cases": [
            {
                "id": case["id"],
                "title": case["title"],
                "status": case["status"],
                "expected": case["expected"],
                "actual": None,
                "source_sha": None,
                "captured_at": None,
                "device_id": None,
                "operation_id": None,
                "audit_ref": None,
            }
            for case in CASES
        ],
    }


def render_matrix() -> str:
    lines = [
        "# Stage 11 device and provider matrix",
        "",
        "Not a freeze. Every row is pending. CI and simulators are not listed as passes.",
        "",
        "| Id | Journey | Status | Expected |",
        "| --- | --- | --- | --- |",
    ]
    for case in CASES:
        lines.append(f"| `{case['id']}` | {case['title']} | `{case['status']}` | {case['expected']} |")
    lines.append("")
    return "\n".join(lines)


def _require(packet: dict, key: str) -> str:
    value = packet.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Stage11Rejection(f"missing_{key}")
    return value.strip()


def submit(register: dict, packet: dict) -> dict:
    """Accept one real PASS, FAIL, or BLOCKED packet. Reject anything else."""
    verdict = _require(packet, "verdict")
    if verdict not in {"PASS", "FAIL", "BLOCKED"}:
        raise Stage11Rejection("verdict_not_a_result")
    case_id = _require(packet, "case_id")
    row = next((item for item in register["cases"] if item["id"] == case_id), None)
    if row is None:
        raise Stage11Rejection("unknown_case")
    if packet.get("evidence_class") not in {"real_device", "production_like"}:
        raise Stage11Rejection("evidence_class_is_not_physical")
    if packet.get("form") != "physical":
        raise Stage11Rejection("form_is_not_physical")
    blob = json.dumps(packet, sort_keys=True, ensure_ascii=False).lower()
    blob = re.sub(r"[\u200b\u200c\u200d\ufeff]|\\u200[bcd]|\\ufeff", "", blob)
    compact = re.sub(r"[\s._-]+", "", blob)
    forbidden = tuple(re.sub(r"[\s._-]+", "", word) for word in (*_FORBIDDEN, "emulated", "simulated", "github actions", "github-actions"))
    if any(word in compact for word in forbidden) or re.search(r"ubuntu\d|macos\d|windows20\d\d", compact):
        raise Stage11Rejection("not_a_physical_environment")
    runner = _require(packet, "runner").lower()
    if runner in _HOSTED_RUNNERS or "github-hosted" in runner:
        raise Stage11Rejection("hosted_runner_is_not_physical")
    source_sha = _require(packet, "source_sha")
    if not _SHA.fullmatch(source_sha):
        raise Stage11Rejection("source_sha_not_exact")
    captured_at = _require(packet, "captured_at")
    if "T" not in captured_at:
        raise Stage11Rejection("missing_timestamp")
    device_id = _require(packet, "device_id")
    operation_id = _require(packet, "operation_id")
    _require(packet, "platform")
    _require(packet, "os_version")
    _require(packet, "expected")
    actual = _require(packet, "actual")
    audit_ref = _require(packet, "audit_ref")
    if "PENDING_OWNER" in row["status"] or case_id == "S11-ESTOP-01":
        if packet.get("owner_attestation") != "present":
            raise Stage11Rejection("owner_gate_open")
    if packet.get("owner_attestation") == "present" and not _require(packet, "owner_actor"):
        raise Stage11Rejection("missing_owner_actor")
    row["status"] = verdict
    row["actual"] = actual
    row["source_sha"] = source_sha
    row["captured_at"] = captured_at
    row["device_id"] = device_id
    row["operation_id"] = operation_id
    row["audit_ref"] = audit_ref
    return row


def write_register(path: Path) -> dict:
    register = blank_register()
    path.write_text(json.dumps(register, indent=2) + "\n", encoding="utf-8")
    return register
