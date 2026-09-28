# Personal AI — W7 Safe Computer Operator Checkpoint

Date: 2026-09-15

## Frozen validated prior tranches

- W7.1 Durable Operator Transaction Core: **IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED**.
- W7.2 Observation Safety / Sensitive Evidence: **IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED** at docs head `2a05e1da4777cdb2393759bd650b264735b1ec97`.
- W7.3 Allowlists and Data-Safety Policies: **IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED** at docs head `72408596db75b3e07b031ddc9a86502a0177902e`.
- W7.4 Safe Browser Operator: **IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED** at docs head `745952cbdc0ab25b93db6dbb3e5324b48fe7837b`.
- W7.5 Safe Desktop and File Operator: **IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED** at docs head `acbbefea2ad6d46406ee05f9d2a44676503b3b59`.

None of these automated classifications imply physical-device, production or live-OAuth verification.

## W7.6 — Verification and Recovery

Baseline SHA: `acbbefea2ad6d46406ee05f9d2a44676503b3b59`.

Validated shared implementation SHA: `38eeae2fc7f609ebc7d3e8681833885b8d35310d`.

The candidate is a direct descendant of the W7.5 docs baseline, 17 commits ahead, with a net implementation delta of exactly 11 files:

- `recovery/cross_operator.py`
- `recovery/operator_recovery.py`
- `recovery/recovery_authority.py`
- `tests/test_w76_adversarial.py`
- `tests/test_w76_hardening.py`
- `tests/test_w76_recovery.py`
- `tests/test_w76_release_gate.py`
- `tools/builtins.py`
- `tools/recovery.py`
- `tools/registry.py`
- `ui/settings_panel.py`

No Home V1/AI Core, W7.4 browser-operator, W7.5 desktop/file-operator, deployment, Railway, production or OAuth file is part of the W7.6 net implementation delta.

### Authority and schema

W7.6 does not create a second transaction authority. It extends the same W7.1 `operator-transactions.sqlite3` authority with additive recovery tables. The recovery schema version is **73**; 72→73 upgrade is additive, older runtime state restores correctly, and no downgrade assumption is introduced.

Trusted Action Core remains approval/reauthentication authority, W7.3 remains default-deny policy/permit authority, and Emergency Stop remains authoritative.

### Dispatch integrity

Side-effect uncertainty is journaled durably before dispatch. Dispatch attempts bind transaction, action identity, operation class, idempotency key, worker identity and fencing token. Duplicate idempotency keys return the existing attempt rather than creating a second side effect. Recovery workers use expiring leases and monotonically advancing fencing tokens; stale/expired workers fail closed. Emergency Stop prevents new dispatch.

### Verification contract

Verification records bind transaction, action, dispatch and idempotency identity. They persist verifier identity/version, precondition, expected postcondition, observed postcondition, bounded evidence references, integrity checksum, verification timestamp/fresh-until, result, explanation and bounded confidence where applicable.

Shared outcomes include `verified_success`, `verified_no_effect`, `verified_partial`, `verified_failure`, `unknown_outcome`, `cancelled_before_dispatch`, `blocked_before_dispatch` and `recovery_review_required`. Unknown outcome never becomes implicit success. Stale or mismatched evidence cannot authorize retry.

### Retry policy

Consequential operations are never blindly retried: form submission, email/message send, external upload, share/public publish, delete/destructive delete, permission/security-setting modification, purchase, financial transfer and legal acceptance. `application_input` is also no-automatic-retry.

Fresh objective `verified_no_effect` evidence can only make a retry eligible for non-consequential classes; consequential classes still require fresh governance. Unknown, partial, stale or unverified outcomes fail closed to recovery review.

### Compensation

Compensation is a distinct side effect and cannot reuse the original action. Compensation categories are explicit: automatically reversible, compensation available, manual recovery only, or irreversible. Manual/irreversible categories cannot be automated.

Automatable compensation must pass current W7.3 policy, consume an exact temporary permit once, enforce owner approval and recent reauthentication when required, and link a separate compensation action. Permit replay fails. Compensation receives its own verification; mismatch or uncertain outcome returns to recovery review.

### Owner decisions / recovery UI

Recovery decisions bind transaction, owner, device, session, current security epoch and nonce. Replayed nonces, wrong device/session and stale security epochs fail closed. Settings → Activities exposes bounded recovery review/reporting; Home V1 and AI Core are not redesigned.

### Evidence/privacy

Recovery redaction excludes secret/token/password/cookie/authorization, raw clipboard content, sensitive DOM and screenshot bytes. Evidence references reject traversal and are bounded. File paths/download names are represented by SHA-256 references where raw identifiers are unnecessary. No background monitoring or hidden bypass is added.

### Validation

Full repository exact shared implementation-head result: **778 passed, 8 warnings**.

`pip check`: PASS.

`compileall`: PASS.

Reliability/Security: dependency audit PASS, full pytest PASS, 45-second soak PASS, isolated encrypted backup/restore qualification PASS.

Package Validation: Ubuntu, macOS and Windows jobs PASS.

P3 iPhone PWA: integration/security workflow PASS, including insecure-production-default fail-closed check.

iOS Companion: simulator build/test and unsigned simulator artifact PASS. This is **not physical iPhone verification**.

### Exact shared implementation workflows

| Workflow | Run | Run ID | Result |
| --- | ---: | ---: | --- |
| CI | #828 | `34932656123` | PASS |
| Reliability and Security | #226 | `34932656078` | PASS |
| P3 iPhone PWA | #186 | `34932656117` | PASS |
| Android Instrumentation | #225 | `34932656134` | PASS |
| Package Validation | #225 | `34932656157` | PASS |
| iOS Companion | #207 | `34932656154` | PASS |

Implementation gate: **6/6 PASS**.

### Stray temporary-file factual record

`tmp_should_not_create` was introduced by `5ac81b382777c4b6b1709a4e4669723f54592ea7`, contained only `x`, and was removed 18 seconds later by `3223ef7f9016f2418ca09c148de06c49834fe9e3` (`W7.5: remove stray connector test file`). It is absent from the W7.5 final tree and W7.6 implementation tree; final validated package evidence has no matching packaged path/name. No new evidence requires further investigation.

## Current classification before documentation-head validation

W7.6 is:
- **IMPLEMENTED**
- **INTEGRATED**
- **IMPLEMENTATION-HEAD AUTOMATED VALIDATED**
- **DOCUMENTATION-HEAD VALIDATION PENDING**

Not claimed: **REAL-WORLD WINDOWS VERIFIED**, **PHYSICAL-DEVICE VERIFIED**, **PRODUCTION VERIFIED** or **LIVE OAUTH VERIFIED**.

## Production / infrastructure boundary

Production, Railway and the existing iPhone qualification service remain unchanged. W6 live Google OAuth/account qualification remains blocked/deferred because isolated paid qualification infrastructure is owner-deferred. W7.6 is repository/CI qualification only.

After the documentation-only head independently passes all six required workflows, W7.6 may be classified **IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED**, followed by the authoritative W7 completion audit.
