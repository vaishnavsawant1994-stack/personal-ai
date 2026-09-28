# Stage-8 Adversarial Inventory — Deepened (28 September 2026)

Branch: `fix/connector-scope-auth-fail-closed` (recovery TOCTOU + api.py restore + connector/epoch/workflow hostility).

An item is closed only when a hostile regression exists **and** the production path fails closed under that attack, with exact-head evidence.

## Status legend

| Status | Meaning |
| --- | --- |
| CLOSED | Hostile test + production fail-closed + checkpoint evidence |
| REPAIRED_PENDING_GATE | Production repaired / tests added; needs exact-head 6/6 |
| OPEN | Still requires coverage or hardening |
| DEFERRED_ARCH | Architecture track; not a demonstrated exploit |

---

## A. Recovery / backup / restore

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| A1 | Backup create path escape | CLOSED | |
| A2 | Restore destination existing symlink | CLOSED | |
| A3 | Restore parent-symlink TOCTOU | REPAIRED_PENDING_GATE | |
| A4 | Rollback vs data-root checks | REPAIRED_PENDING_GATE | |
| A5 | Failed restore external residue | REPAIRED_PENDING_GATE | |
| A6 | Security authority non-restorable | CLOSED | |
| A7 | Symlinked sources excluded from backup | CLOSED | |

## B. Authorization / scopes

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| B1 | Owner APIs require callable authorizer | CLOSED | |
| B2 | Connector APIs require callable authorizer | CLOSED | |
| B3 | Continuity handoff revalidation | CLOSED | |
| B4 | Device authorize implies is_active | CLOSED | |
| B5 | Auth parity modern vs legacy | REPAIRED_PENDING_GATE | Fail-closed authorize predicate parity test |
| B6 | Stale approval after security epoch | REPAIRED_PENDING_GATE | Epoch invalidates pending/approved; approve/consume/dispatch fail closed |

## C. Connector → Knowledge

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| C1–C5 | write/private/approved/dedupe/authorize | CLOSED | |
| C6 | Per-source min sensitivity | DEFERRED_ARCH | |
| C7 | never_store end-to-end | REPAIRED_PENDING_GATE | |
| C8 | Sheets parity with Drive | REPAIRED_PENDING_GATE | |

## D. Workflow / automation authority

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| D1 | Run visibility binding | CLOSED (partial) | |
| D2 | Missing run_binding fails closed | REPAIRED_PENDING_GATE | 503 in api.py |
| D3 | Tool/shell step laundering | REPAIRED_PENDING_GATE | Only condition/set/emit/prompt; other kinds fail |
| D4 | E-stop blocks workflow | CLOSED | |
| D5 | Workflow list unfiltered | OPEN | Product intent for single-owner |

## E. Emergency Stop

| ID | Status |
| --- | --- |
| E1–E3 | CLOSED |

## F. Input / URL / SQL

| ID | Status |
| --- | --- |
| F1–F3 | CLOSED |
| F4 Browser operator redirect | OPEN |

## G. Audit / leakage

| ID | Status |
| --- | --- |
| G1 | CLOSED (partial) |
| G2 False-success | OPEN |
| G3 Error path leakage | OPEN |

## H. Continuity / devices

| ID | Status |
| --- | --- |
| H1–H3 | CLOSED |

---

## Queue to freeze Stage 8

1. Exact-head 6/6 green on current branch head.
2. Promote all REPAIRED_PENDING_GATE → CLOSED with CI evidence.
3. Resolve or DEFER D5, F4, G2, G3 with owner-visible rationale.
4. Formal Stage-8 freeze SHA + handoff to Stage 9 charter (`docs/STAGE9_*`).

## Closure rule

Stage 8 closes only when OPEN high-severity items are gone or deferred, REPAIRED items have exact-head evidence, and 6/6 families are green on one freeze SHA.
