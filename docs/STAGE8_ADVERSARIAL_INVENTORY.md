# Stage-8 Adversarial Inventory — Deepened (28 September 2026)

Branch head at inventory time: continue from `45674032…` + follow-on patches on `fix/connector-scope-auth-fail-closed`.

This document is the living Stage-8 inventory. An item is closed only when a hostile regression exists **and** the production path fails closed under that attack, with exact-head evidence.

## Status legend

| Status | Meaning |
| --- | --- |
| CLOSED | Hostile test + production fail-closed + prior/ current Stage-8 checkpoint evidence |
| REPAIRED_PENDING_GATE | Production repaired; needs exact-head 6/6 confirmation |
| OPEN | Attack surface still requires hostile coverage or production hardening |
| DEFERRED_ARCH | Architectural gap; not a demonstrated exploit; track for Stage 9/10 |

---

## A. Recovery / backup / restore

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| A1 | Backup create path escape (absolute/traversal/symlink parent) | CLOSED | Confined to backup_dir; symlink parents rejected |
| A2 | Restore destination existing symlink | CLOSED | `_safe_destination` / pre-write checks |
| A3 | Restore parent-symlink TOCTOU after validation | REPAIRED_PENDING_GATE | Re-validate after mkdir and before open/replace; no-follow component walk |
| A4 | Rollback copies must not inherit data-root checks | REPAIRED_PENDING_GATE | `enforce_data_root` only on restore writes into owner data |
| A5 | Failed hostile restore leaves no external residue | OPEN | Hostile residual-file test added; confirm on exact-head |
| A6 | Security authority non-restorable | CLOSED | NON_RESTORABLE_SECURITY_NAMES skipped |
| A7 | Symlinked source files excluded from backup | CLOSED | `_eligible` skips symlinks |

## B. Authorization / scopes

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| B1 | Owner APIs require callable scope authorizer | CLOSED | Fail 503 when authorize missing |
| B2 | Connector APIs require callable scope authorizer | CLOSED | Same pattern in connector_router |
| B3 | Continuity handoff revalidates at commit boundary | CLOSED | Revocation race repaired |
| B4 | Device authorize implies is_active | CLOSED | `authorize` checks revoked |
| B5 | Authorization parity modern vs legacy transports | OPEN | Audit remaining legacy routes for identical scope names and fail-closed behavior |
| B6 | Stale session after security epoch advance | OPEN | Approvals invalidate; confirm PWA/cloud session surfaces cannot reuse pre-epoch tokens for consequential actions |

## C. Connector → Knowledge

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| C1 | knowledge:write required (not device:admin alone) | CLOSED | |
| C2 | knowledge:private required for private access_class | CLOSED | |
| C3 | Explicit approved=true required | CLOSED | 409 otherwise |
| C4 | Checksum dedupe binds access_class | CLOSED | Private cannot inherit owner classification |
| C5 | Missing authorize fails closed | CLOSED | 503 |
| C6 | Per-source minimum sensitivity classification | DEFERRED_ARCH | No canonical source→min-class map yet; track as architecture, not auto-vuln |
| C7 | never_store honored end-to-end | OPEN | Confirm no durable object/chunk when never_store=True |
| C8 | Sheets path parity with Drive | OPEN | Same approval/scope rules exist; add hostile parity tests |

## D. Workflow / automation authority

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| D1 | Workflow run visibility device/session binding | CLOSED (partial) | Filters by owner/device/session when binding present |
| D2 | Missing run_binding fails closed | REPAIRED_PENDING_GATE | Was fail-open (`return rows`); now 503 |
| D3 | Tool authority laundering via workflow step params | OPEN | Ensure step tool names cannot escalate beyond device scopes / approval policy |
| D4 | Emergency Stop blocks workflow continuation | CLOSED (prior) | recovery_required transitions |
| D5 | Workflow list unfiltered | OPEN | `/workflows` returns all workflows to any workflow:read device — confirm product intent for single-owner |

## E. Emergency Stop / cloud convergence

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| E1 | PWA E-stop vs established cloud session | CLOSED | Shared stop predicate |
| E2 | Cloud command returns 423 when stopped | CLOSED | |
| E3 | Approvals blocked under E-stop | CLOSED | |

## F. Input / URL / SQL

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| F1 | Legacy web open rejects private/metadata/file URLs | CLOSED | test_stage8_web_url_security |
| F2 | Dynamic SQL identifier injection in workflow/ops/oauth | CLOSED | test_stage8_sql_identifier_guards |
| F3 | JSON body size/nesting limits on control API | CLOSED | bounded_mapping / limits in api.py |
| F4 | Browser safe operator redirect / open redirect | OPEN | Extend hostile URL tests to browser operator if separate path |

## G. Audit / information leakage

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| G1 | Connector events do not embed file body | CLOSED (partial) | Stage-8 test asserts SENTINEL not in events |
| G2 | False-success tool results | OPEN | Model/tool verified=false must not become owner-visible completed |
| G3 | Error messages do not leak secrets/paths outside data root | OPEN | Sample BackupError / ConnectorError surfaces |

## H. Continuity / devices

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| H1 | Handoff revocation race | CLOSED | |
| H2 | Revoked offline device cannot activate | CLOSED (prior P8) | |
| H3 | Cross-device continuity is not authority transfer | CLOSED (design) | Automated; physical deferred |

---

## Immediate Stage-8 work queue (priority order)

1. Confirm exact-head 6/6 on recovery TOCTOU + rollback fix lineage.
2. Land D2 fail-closed workflow binding + hostile regression.
3. A5 residual-file assertion after TOCTOU failure.
4. C7 never_store end-to-end hostile test.
5. C8 Sheets parity hostile tests.
6. B5/B6 authorization parity + epoch/session residual.
7. D3 tool laundering via workflow steps.
8. G2/G3 audit/false-success sampling.
9. Exhaust OPEN items or explicitly DEFER with rationale.
10. Final Stage-8 freeze SHA + formal closure note.

## Closure rule (unchanged)

Stage 8 is **not** closed until:

- All CLOSED/REPAIRED items have exact-head evidence,
- OPEN items are either closed or explicitly deferred with owner-visible rationale,
- Full pytest + Reliability & Security + six workflow families are green on one freeze SHA,
- No unresolved high-severity fail-open remains in recovery, auth, connector→Knowledge, or workflow visibility.
