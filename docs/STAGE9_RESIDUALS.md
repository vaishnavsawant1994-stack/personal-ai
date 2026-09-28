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

## R2 — Emergency Stop durable authority is the tool registry

`ToolRegistry` persists the flag in `runtime-controls.sqlite3`. A new process reading that file stays stopped. `tests/test_stage9_emergency_stop_authority.py` shows a fresh cloud session row does not clear that stop, and a cloud owner write updates the tool row.

The cloud `cloud_state` value is still written by the official setters so the two flags cannot disagree on success. It is not a second way to turn the stop off. One sqlite table was not deleted.

`GET /capabilities/api/status` and `POST /iphone/api/logout` are recorded gaps, not Emergency Stop authorities.

## R3 — Approval class is single; openers are several

`class ApprovalManager` exists only in `security/approvals.py`. Production code opens that class from `agent/executor.py`, `integrations/runtime.py`, and `tools/registry.py` (epoch read and `advance_security_epoch` on Emergency Stop). Same class, same file name `trusted-actions.sqlite3` where a data root is set. This is not a second implementation. It is also not a proof that every process shares one open connection.

## R4 — Still deferred from Stage 8

C6 per-source sensitivity map, D5 unfiltered `GET /workflows`, F4 browser-operator URLs. Unchanged at the Stage 9 freeze. D5 and F4 were closed by later commits. C6 remains deferred.

## R5 — Not physical

Nothing in this note is a device, OAuth, or live Emergency Stop proof. That remains Stage 11.
