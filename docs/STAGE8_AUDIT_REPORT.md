# Stage-8 Formal Audit Report

**Branch:** `fix/connector-scope-auth-fail-closed`  
**Head baseline:** `94626b41cdbb33b103466255e5ea8cd9555f6482` (+ this audit commit)  
**Date:** 28 September 2026  
**Auditor posture:** Hostile / fail-closed; no Stage-8 freeze without exact-head evidence

---

## 1. Executive verdict

| Question | Answer |
| --- | --- |
| Is Stage 8 **frozen**? | **No** |
| Is the control plane intact? | **Yes** — `server/api.py` full (workflows, cloud, device WS, binding fail-closed) |
| Are high-severity recovery/auth/Knowledge defects addressed in code + tests? | **Yes** — pending CI promotion |
| Remaining OPEN items | Product-intent or lower-severity; explicit deferrals below |
| Stage 9 ready to execute? | **Not until** Stage 8 freeze SHA + 6/6 green |

---

## 2. Work landed this engagement

1. **Recovery TOCTOU** — parent-symlink swap after validation fail-closed; rollback does not inherit data-root checks
2. **Control API restore** — truncated `server/api.py` replaced with full module + workflow binding 503
3. **Connector → Knowledge** — never_store, Sheets parity, private/write/approved gates
4. **Security epoch** — invalidate pending/approved; approve/consume/dispatch fail closed
5. **Workflow authority** — reject `tool`/`shell` step kinds; no laundering past prompt path
6. **Stage 9 charter** — threat model, authority map, census template, composition harness (docs only)
7. **Audit integrity** — verified=false preserved; BackupError non-success language

---

## 3. Stage-8 hostile test inventory

| File | Covers |
| --- | --- |
| `tests/test_stage8_connector_knowledge_authority.py` | C1–C5 |
| `tests/test_stage8_never_store_and_sheets_parity.py` | C7–C8 |
| `tests/test_stage8_restore_residue.py` | A5 |
| `tests/test_stage8_epoch_and_workflow_authority.py` | B5–B6, D3 |
| `tests/test_stage8_workflow_binding_fail_closed.py` | D2 invariant |
| `tests/test_stage8_web_url_security.py` | F1 |
| `tests/test_stage8_sql_identifier_guards.py` | F2 |
| `tests/test_stage8_audit_integrity.py` | G2–G3 |

---

## 4. Inventory status

### CLOSED

A1, A2, A6, A7, B1–B4, C1–C5, D1 (partial), D4, E1–E3, F1–F3, G1 (partial), H1–H3

### REPAIRED_PENDING_GATE (need exact-head 6/6)

| ID | Item |
| --- | --- |
| A3–A5 | Restore TOCTOU, rollback, residue |
| B5–B6 | Auth parity; security epoch |
| C7–C8 | never_store; Sheets parity |
| D2–D3 | run_binding 503; step kind laundering |
| G2–G3 | verified=false retention; safe BackupError |

### Explicitly DEFERRED

| ID | Item | Rationale |
| --- | --- | --- |
| C6 | Per-source minimum sensitivity map | Architecture; access_class gates remain |
| D5 | `/workflows` list unfiltered | Single-owner product intent; runs stay binding-filtered |
| F4 | Browser operator open-redirect | F1 covers legacy web; browser operator → Stage 9 census |
| — | Physical/live qualification | Stage 11 only |

---

## 5. Branch health

| Check | Result |
| --- | --- |
| `server/api.py` not truncated | Pass |
| Workflow runs missing binding → 503 | Pass |
| Recovery symlink containment | Pass (code) |
| Stage 9 docs | Present |
| Stage 8 inventory | Present |
| Exact-head CI 6/6 | **Not verified in this session** |

---

## 6. Required sequence (proper / project rules)

1. Green exact-head: full pytest + Reliability & Security + six workflow families.
2. Promote `REPAIRED_PENDING_GATE` → `CLOSED` only with that evidence.
3. Publish Stage-8 freeze SHA.
4. Enter Stage 9 per `docs/STAGE9_THREAT_MODEL_AND_PLAN.md`.
5. Do not claim Stages 10–12 or production readiness.

---

## 7. Honesty constraints

- Stage 8 is **not** complete without CI.
- The product is **not** 100% ready (Stage 11 physical gates are owner-controlled).
- Model/agent/connector are never authority.

**Posture:** Fail closed; inventory over optimism.
