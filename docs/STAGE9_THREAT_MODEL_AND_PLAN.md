# Stage 9 — Threat Model, Canonical Authority Map, and Integration Plan

**Status:** READY TO ENTER only after Stage 8 high-severity OPEN items are closed or explicitly deferred with owner-visible rationale.  
**Date:** 28 September 2026  
**Product rule:** Stage 9 is A–Z V1 **integration / canonicalization**. It is not a feature factory and not a second Stage 8.

---

## 1. Purpose

Stage 9 exists to make the product behave as **one** system:

- One authoritative concept each for identity, device trust, permissions, approvals, execution, Emergency Stop, Memory, Knowledge, continuity, audit, model routing, and recovery.
- All surfaces (desktop, PWA, Android, iOS, cloud, connectors, P6/P10) compose through those authorities.
- No dual live implementations of the same security concept.
- No residual weaker routes left reachable “for compatibility” without parity.

Threat modeling for Stage 9 focuses on failures **caused by integration itself**: split-brain, residual paths, composition shortcuts, migration hazards, and consent drift.

---

## 2. Preconditions (do not skip)

| Gate | Requirement |
| --- | --- |
| Stage 8 recovery | Parent-symlink TOCTOU + rollback path fail-closed; residual external write denied; exact-head evidence |
| Stage 8 auth | Missing `authorize` fails closed on owner and connector APIs |
| Stage 8 Knowledge | `knowledge:write` / `knowledge:private` / `approved=true` / access_class-bound dedupe |
| Stage 8 workflow | Run visibility binding; missing `run_binding` fails closed on all transports |
| Stage 8 E-stop | Shared stop predicate across PWA and cloud |
| Branch health | Control API (`server/api.py`) complete and non-truncated; 6/6 family green on freeze candidate |

If any high-severity Stage 8 item remains OPEN, Stage 9 dual-path work multiplies risk. Finish or defer explicitly first.

---

## 3. Canonical authority map

Each row is the **only** allowed writer of that concept after Stage 9. Readers may be many; writers must be one module (or one façade that owns the store).

| Concept | Canonical module | Primary store | Surfaces that must call it (not reimplement) |
| --- | --- | --- | --- |
| Device identity & scopes | `devices/registry.py` | `devices.sqlite3` | Pairing, PWA cookies, cloud session, WS, companion |
| Continuity threads | `devices/continuity.py` | continuity DB under data dir | `/continuity/*`, device WS, companions |
| Device transport | `devices/gateway.py` | process + registry metadata | Desktop WS, push registration |
| Approvals & security epoch | `security/approvals.py` | approval tickets + `approval_security_state` | Executor, cloud approval, workflow approval, PWA |
| Request context | `security/request_context.py` | request-scoped | PWA/connector middleware |
| Policy / risk gateway | `security/policy_gateway.py` | policy inputs | W7 / executor path |
| PWA sessions | `security/pwa_sessions.py` | `pwa-sessions.sqlite3` | PWA only |
| Cloud sessions | `cloud_runtime` session store | `cloud-sessions.sqlite3` | Cloud relay only |
| Emergency Stop | shared runtime control (ToolRegistry / runtime-controls) | `runtime-controls.sqlite3` (or equivalent single flag) | PWA, cloud, executor, workflows |
| Trusted action core (W7) | executor + tool registry path | execution records | All tool execution |
| Memory | `memory/*` | memory SQLite | Chat, cloud memory search, audit projections |
| Knowledge | `knowledge/store.py` + `knowledge/governance.py` | `knowledge.sqlite3` + objects | Owner upload, connector ingest, search |
| Connectors OAuth/state | `integrations/*` | `connectors.sqlite3` | Connector API, OAuth callback |
| Connector→Knowledge bridge | `integrations/knowledge_bridge.py` | via Knowledge authority | Drive/Sheets ingest only |
| Workflows | `automation/engine.py` | workflow SQLite | `/workflows/*`, P6 hooks |
| Backup/restore | `recovery/backup.py` | archives under `backups/` | Owner recovery UX only |
| Root key / keychain | `security/keychain.py` | platform keychain | Backup encryption only |
| Model routing (P9) | `models/*` | config + runtime status | Executor chat path only (compute, not permission) |
| Ops / autonomy (P6/P10) | `future_intelligence/*`, agent planners | ops stores | Plan/coordinate only; must call W7 + approvals |
| Activities / audit projection | memory audit + activities projection | memory audit tables | Cloud activities, dashboard |
| Benchmark / qualification | `qualification/*` | qualification stores | `/benchmark/*` |

### Non-restorable security names (must remain)

`devices.sqlite3`, `pwa-sessions.sqlite3`, `cloud-sessions.sqlite3`, `trusted-actions.sqlite3`, `runtime-controls.sqlite3`, operator policy/transaction stores, `owner-access.sqlite3`, `connectors.sqlite3`.

Ordinary data restore must never resurrect revoked trust, sessions, or epochs.

---

## 4. Composition law (non-negotiable)

```
Owner consent
    → Device trust + scopes + session + security epoch
        → Approvals / Emergency Stop
            → W7 execution (tools)
                → side effects

Memory authority  ──┐
Knowledge authority ┼─ separate; orchestration may query both; neither absorbs the other
Life Graph          ┘ projections only

P9 model routing = compute choice only
P6 / P10          = plan and coordinate only
Connectors        = external I/O only; Knowledge write requires explicit owner approval + scopes
```

**Forbidden back-edges:** model, agent, connector, or workflow step must never grant device trust, advance/ignore security epoch, clear E-stop, or write Memory/Knowledge without the canonical APIs and checks.

---

## 5. Threat model (Stage 9 lens)

### T1 — Dual-authority / split-brain

| ID | Threat | Detection | Mitigation |
| --- | --- | --- | --- |
| T1.1 | Two E-stop flags (PWA vs cloud) | Integration test both surfaces | Single predicate; one store |
| T1.2 | Process-memory vs durable approvals | Restart mid-approval | Durable tickets only |
| T1.3 | Dual session models disagree on revocation | Revoke device; hit all transports | Registry `is_active` + session stores invalidated together |
| T1.4 | Two Knowledge writers bypass governance | Code search for ingest paths | Only `KnowledgeAuthority` / store.ingest |

### T2 — Residual weaker routes

| ID | Threat | Detection | Mitigation |
| --- | --- | --- | --- |
| T2.1 | Legacy `/command` vs cloud/PWA chat scope skew | Entrypoint census | Same `auth_device` scopes or delete |
| T2.2 | Workflow list unfiltered while runs filtered | Hostile multi-device test | Product decision: filter or document single-owner |
| T2.3 | Old companion builds call deleted APIs | Version skew tests | Minimum build; fail closed |
| T2.4 | Deprecated OAuth/state path | Route inventory | Delete or proxy to canonical |

### T3 — Composition elevation

| ID | Threat | Detection | Mitigation |
| --- | --- | --- | --- |
| T3.1 | P10 schedules tool without W7/approval | Static import + scenario | Planner cannot import operators |
| T3.2 | Workflow step tool name launders scopes | Hostile workflow fixture | Step execution goes through same approval policy as chat tools |
| T3.3 | Connector uses `device:admin` for Knowledge | Stage 8 regressions | Keep `knowledge:write` / `knowledge:private` |
| T3.4 | Model “verified” treated as owner success | Activities tests | `verified` / `failure_code` required |

### T4 — Surface drift

| ID | Threat | Detection | Mitigation |
| --- | --- | --- | --- |
| T4.1 | Desktop file tools vs PWA policy mismatch | Consent matrix | Explicit per-surface policy table |
| T4.2 | Offline companion ignores revocation | Reconnect tests | Revalidate scopes before consequential action |
| T4.3 | Cloud CORS / origin drift | Config review | No wildcard origins (already enforced) |

### T5 — Memory / Knowledge merge hazard

| ID | Threat | Detection | Mitigation |
| --- | --- | --- | --- |
| T5.1 | Unified search leaks private Knowledge | Isolation tests | Default queries exclude private |
| T5.2 | Dedupe across access_class reintroduced | Stage 8 C4 regression | checksum **and** access_class |
| T5.3 | Life Graph from untrusted connector text | Provenance required | No edge without source evidence |

### T6 — Migration / cutover

| ID | Threat | Detection | Mitigation |
| --- | --- | --- | --- |
| T6.1 | Dual-write security tables | Migration review | Single writer after cutover |
| T6.2 | Partial migration of permissions | Crash-mid-migration test | Transactions + version flag |
| T6.3 | Backup layout skew skips security excludes | Restore inspect tests | Keep NON_RESTORABLE list covered |

### T7 — Consent UX broadening

| ID | Threat | Detection | Mitigation |
| --- | --- | --- | --- |
| T7.1 | One “Allow connectors” grants send+ingest | Consent matrix review | Separate scopes and prompts |
| T7.2 | “Remember device” grants full OWNER_SCOPES | Enroll path test | Minimal default scopes |
| T7.3 | Voice continuous mode skips tickets | Voice path test | Same approval authority |

### T8 — False-success / audit integrity

| ID | Threat | Detection | Mitigation |
| --- | --- | --- | --- |
| T8.1 | Activities show completed when verified=false | G2 tests | Schema requires verified |
| T8.2 | E-stop abort hidden on one surface | Multi-surface scenario | recovery_required visible everywhere |
| T8.3 | Error text leaks external paths | Sample BackupError/ConnectorError | Safe messages only |

---

## 6. Entrypoint census framework

See `docs/STAGE9_ENTRYPOINT_CENSUS_TEMPLATE.md`.

---

## 7. Stage 9 work packages (ordered)

### WP0 — Branch hygiene (blocking)

- Restore any truncated control-plane modules.
- Re-green exact-head pytest + Reliability & Security + six workflow families.
- Record Stage 8 freeze SHA or explicit residual deferrals.

### WP1 — Authority map freeze

- Publish this map in-repo (this document).
- Add CI lint where practical: forbidden dual writers for security stores (start with approvals + E-stop + devices).

### WP2 — Entrypoint census + residual burn-down

- Complete entrypoint inventory.
- Delete or proxy residual routes.
- Parity tests for any proxy that must remain.

### WP3 — Composition harness

See `docs/STAGE9_COMPOSITION_HARNESS.md` (scenarios H1–H12).

### WP4 — Consent matrix

- Table: UI action → scopes granted → durable artifact.
- No scope expansion without new tests.

### WP5 — Migration kit (only if schema changes required)

- Versioned, transactional migrations.
- No dual-write for security stores.
- Backup compatibility matrix updated.

### WP6 — Audit schema freeze

- Unified activity fields: identity, status, verified, failure_code, security_epoch, device/session binding.
- False-success forbidden tests.

### WP7 — Stage 9 freeze

- Single SHA where census, harness, and map are consistent.
- Handoff note to Stage 10 (freeze that SHA; stop feature churn).

---

## 8. Explicit non-goals (Stage 9)

- New major connectors or providers
- New autonomy features beyond making P10 obey composition law
- Merging Memory and Knowledge into one store
- Letting the model decide whether approval is required
- Physical/live qualification (Stage 11)
- Marketing/readiness packaging (Stage 12)

---

## 9. Exit criteria

| # | Criterion | Evidence |
| --- | --- | --- |
| 1 | Canonical authority map matches code | This doc + module review |
| 2 | No dual live writers for security concepts | Census + CI/lint or test |
| 3 | Residual routes deleted or parity-proxied | Census sheet complete |
| 4 | Composition harness green on one SHA | H1–H12 |
| 5 | Memory/Knowledge boundary preserved | Isolation regressions |
| 6 | Consent matrix reviewed; no silent scope expansion | WP4 |
| 7 | Audit never false-success | WP6 tests |
| 8 | Exact-head 6/6 still green | CI |
| 9 | Stage 10 freeze SHA designated | Release note |

---

## 10. Relationship to other stages

| Stage | Role relative to Stage 9 |
| --- | --- |
| 1–7 | Built and closed foundations |
| **8** | Adversarial qualification of boundaries (input) |
| **9** | Integrate into one product without dual authorities (this doc) |
| **10** | Freeze the integrated SHA |
| **11** | Physical/live proof on that freeze |
| **12** | Owner-facing readiness |

---

## 11. Immediate next actions for maintainers

1. Close Stage 8 P0 items (including any broken `server/api.py` on working branches).
2. Treat this document as the Stage 9 charter.
3. Start WP1–WP2 (map + census) before any cleanup refactors that move security logic.
4. Do not open Stage 10 until §9 exit criteria are met.

**Rule of thumb:** If a change creates a second way to approve, stop, trust a device, write Knowledge, or clear E-stop, it is a Stage 9 regression — fail the change, do not finish later.
