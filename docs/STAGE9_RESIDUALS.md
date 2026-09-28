# Stage 9 residual and weaker-path notes

**Status:** Open. These notes do not close Stage 9.  
**Evidence base:** census at `0024a2b`, which is exact-head 6/6. Later analysis commits do not inherit that result.

## R1 — Duplicate route definitions

The census has 191 decorators and 7 duplicate method+path keys. Every duplicate is the historical PWA handler plus the canonical module:

| Method | Path | Definitions |
| --- | --- | --- |
| POST | `/iphone/api/voice/turn` | `conversation_voice_api.py`, `iphone_pwa.py` |
| POST | `/iphone/api/voice/barge` | `conversation_voice_api.py`, `iphone_pwa.py` |
| POST | `/iphone/api/voice/client-event` | `conversation_voice_api.py`, `iphone_pwa.py` |
| POST | `/iphone/api/approval/{approval_id}/approve` | `approval_api.py`, `iphone_pwa.py` |
| POST | `/iphone/api/approval/{approval_id}/reject` | `approval_api.py`, `iphone_pwa.py` |
| GET | `/iphone/api/conversations` | `conversation_voice_api.py`, `iphone_pwa.py` |
| GET | `/iphone/api/conversations/{conversation_id}` | `conversation_voice_api.py`, `iphone_pwa.py` |

Production `server/cloud_app.py` mounts `iphone_pwa_router(..., include_legacy_runtime_routes=False)`. The router default is now **False**, so a caller that omits the flag does not mount the seven historical routes. Isolated P3 tests pass `include_legacy_runtime_routes=True` on purpose. That opt-in is not the production cloud app.

**Remaining:** those handlers still exist for the opt-in. They are not mounted beside the canonical routers unless a caller asks for them.

## R2 — Emergency Stop stores are mirrored, not deleted

Threat T1.1 is reconciled, not erased. One store was not deleted.

Canonical durable flag: `ToolRegistry` → `runtime-controls.sqlite3`.

Cloud session `cloud_state.emergency_stop` is a mirror:

- `cloud_runtime/relay.py` writes the mirror and the tool flag, and returns `emergency_stop_diverged` (503) if they disagree.
- `server/owner_product.py` writes the tool flag and, when `cloud_sessions` is on the runtime, the mirror. It returns 503 if either does not match the requested value.
- Reads in the relay stop if **either** flag is set. A stale mirror cannot reopen a stopped tool path, and a tool stop cannot be missed by the relay.

Isolated tests that have no tool registry still stop on the session mirror alone. That is fail-closed, not a second production writer.

This does not claim a single sqlite table. It claims the two official writers no longer leave the flags diverged on success.

## R3 — Approval class is single; openers are several

`class ApprovalManager` exists only in `security/approvals.py`. Production code opens that class from `agent/executor.py`, `integrations/runtime.py`, and `tools/registry.py` (epoch read and `advance_security_epoch` on Emergency Stop). Same class, same file name `trusted-actions.sqlite3` where a data root is set. This is not a second implementation. It is also not a proof that every process shares one open connection.

## R4 — Still deferred from Stage 8

C6 per-source sensitivity map, D5 unfiltered `GET /workflows`, F4 browser-operator URLs. Unchanged.

## R5 — Not physical

Nothing in this note is a device, OAuth, or live Emergency Stop proof. That remains Stage 11.
