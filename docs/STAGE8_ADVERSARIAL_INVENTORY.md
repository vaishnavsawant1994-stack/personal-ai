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
| A3 | Restore parent-symlink TOCTOU | CLOSED | Exact-head 6/6 at `b17c505` |
| A4 | Rollback vs data-root checks | CLOSED | Exact-head 6/6 at `b17c505` |
| A5 | Failed restore external residue | CLOSED | Exact-head 6/6 at `b17c505` |
| A6 | Security authority non-restorable | CLOSED | |
| A7 | Symlinked sources excluded from backup | CLOSED | |

## B. Authorization / scopes

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| B1 | Owner APIs require callable authorizer | CLOSED | |
| B2 | Connector APIs require callable authorizer | CLOSED | |
| B3 | Continuity handoff revalidation | CLOSED | |
| B4 | Device authorize implies is_active | CLOSED | |
| B5 | Auth parity modern vs legacy | CLOSED | Exact-head 6/6 at `b17c505` |
| B6 | Stale approval after security epoch | CLOSED | Exact-head 6/6 at `b17c505` |

## C. Connector → Knowledge

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| C1–C5 | write/private/approved/dedupe/authorize | CLOSED | |
| C6 | Per-source min sensitivity | DEFERRED_ARCH | |
| C7 | never_store end-to-end | CLOSED | Exact-head 6/6 at `b17c505` |
| C8 | Sheets parity with Drive | CLOSED | Exact-head 6/6 at `b17c505` |

## D. Workflow / automation authority

| ID | Surface | Status | Notes |
| --- | --- | --- | --- |
| D1 | Run visibility binding | CLOSED (partial) | |
| D2 | Missing run_binding fails closed | CLOSED | HTTP 503. Exact-head 6/6 at `b17c505` |
| D3 | Tool/shell step laundering | CLOSED | Exact-head 6/6 at `b17c505` |
| D4 | E-stop blocks workflow | CLOSED | |
| D5 | Workflow list unfiltered | DEFERRED_ARCH | Single-owner product intent |

## E. Emergency Stop

| ID | Status |
| --- | --- |
| E1–E3 | CLOSED |

## F. Input / URL / SQL

| ID | Status |
| --- | --- |
| F1–F3 | CLOSED |
| F4 Browser operator redirect | DEFERRED_ARCH | Stage 9 census. Not closed. |

## G. Audit / leakage

| ID | Status |
| --- | --- |
| G1 | CLOSED (partial) |
| G2 False-success | CLOSED | Exact-head 6/6 at `b17c505` |
| G3 Error path leakage | CLOSED | Exact-head 6/6 at `b17c505` |

## H. Continuity / devices

| ID | Status |
| --- | --- |
| H1–H3 | CLOSED |

---

## Queue to freeze Stage 8

Done for `b17c505`:

1. Exact-head 6/6 green.
2. `REPAIRED_PENDING_GATE` promoted to CLOSED.
3. D5 and F4 deferred with rationale. G2 and G3 closed on the same evidence.
4. Freeze note: `docs/STAGE8_FREEZE.md`.

Stage 9 is entered and not exited (`docs/STAGE9_STATUS.md`). Stages 10–12 are not open.

## Closure rule

Stage 8 closes only when OPEN high-severity items are gone or deferred, REPAIRED items have exact-head evidence, and 6/6 families are green on one freeze SHA.
