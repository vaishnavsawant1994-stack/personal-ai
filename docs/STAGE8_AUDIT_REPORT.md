# Stage-8 Formal Audit Report

**Branch:** `fix/connector-scope-auth-fail-closed`  
**Head baseline:** `b17c5051772b5e82b7a6a208903bb0300bf1e405`  
**Date:** 28 September 2026  
**Auditor posture:** Hostile / fail-closed. Stage 8 is frozen only at the evidence SHA in `docs/STAGE8_FREEZE.md`.

---

## 1. Executive verdict

| Question | Answer |
| --- | --- |
| Is Stage 8 **frozen**? | **Yes, at `b17c505` only** — see `docs/STAGE8_FREEZE.md`. A later commit is not that freeze. |
| Is the control plane intact? | **Yes** — `server/api.py` full (workflows, cloud, device WS, binding fail-closed) |
| Are high-severity recovery/auth/Knowledge defects addressed in code + tests? | **Yes** — promoted CLOSED on exact-head 6/6 |
| Remaining OPEN items | Explicit deferrals only (C6, D5, F4, physical) |
| Stage 9 ready to execute? | **Entered, not exited.** See `docs/STAGE9_STATUS.md`. |

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

A1, A2, A3, A4, A5, A6, A7, B1–B6, C1–C5, C7, C8, D1 (partial), D2, D3, D4, E1–E3, F1–F3, G1 (partial), G2, G3, H1–H3

Promoted from `REPAIRED_PENDING_GATE` on exact-head 6/6 at `b17c5051772b5e82b7a6a208903bb0300bf1e405`: A3–A5, B5–B6, C7–C8, D2–D3, G2–G3.

### REPAIRED_PENDING_GATE

None. The gate was the 6/6 run recorded in `docs/STAGE8_FREEZE.md`.

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
| Exact-head CI 6/6 | **Pass on `b17c505`** — CI, Reliability and Security, P3 iPhone PWA, Android, Package, iOS. See `docs/STAGE8_FREEZE.md`. |

---

## 6. Required sequence (proper / project rules)

1. Exact-head 6/6 recorded at `b17c505`. Done.
2. `REPAIRED_PENDING_GATE` promoted to `CLOSED` with that evidence. Done.
3. Stage-8 freeze SHA published in `docs/STAGE8_FREEZE.md`. Done.
4. Stage 9 may proceed per `docs/STAGE9_THREAT_MODEL_AND_PLAN.md`. It is **not** exited.
5. Do not claim Stages 10–12 or production readiness. Do not merge on this note alone.

---

## 7. Honesty constraints

- Stage 8 is frozen **only** at `b17c505`, not at whatever HEAD is after this note.
- The product is **not** 100% ready (Stage 11 physical gates are owner-controlled).
- Model/agent/connector are never authority.

**Posture:** Fail closed; inventory over optimism.
