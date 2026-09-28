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

Production `server/cloud_app.py` mounts `iphone_pwa_router(..., include_legacy_runtime_routes=False)`, which removes those seven PWA routes. No other duplicate key exists in the census.

Tests still mount the legacy router on purpose. That is not a second production authority.

**Not closed:** a future entrypoint that calls `iphone_pwa_router` with the default `include_legacy_runtime_routes=True` together with the canonical routers would recreate the dual path. The default remains `True`.

## R2 — Emergency Stop is still two stores (blocks Stage 9 exit)

Threat T1.1 is not closed.

`cloud_runtime/relay.py` `set_emergency_stop` writes both:

- `CloudSessionStore.set_emergency_stop` → `cloud_state` key `emergency_stop`
- `tools.set_emergency_stop` → `runtime-controls.sqlite3` plus an approval-epoch advance

`server/owner_product.py` `/iphone/api/system/emergency-stop` calls only `runtime['tools'].set_emergency_stop`. It does not write the cloud session flag.

One owner action can therefore stop tools without setting the cloud flag, and a cloud stop sets both only when it goes through the relay. This is an open split. It is not patched in this pass. No simulated device result is offered as proof.

## R3 — Approval class is single; openers are several

`class ApprovalManager` exists only in `security/approvals.py`. Production code opens that class from `agent/executor.py`, `integrations/runtime.py`, and `tools/registry.py` (epoch read and `advance_security_epoch` on Emergency Stop). Same class, same file name `trusted-actions.sqlite3` where a data root is set. This is not a second implementation. It is also not a proof that every process shares one open connection.

## R4 — Still deferred from Stage 8

C6 per-source sensitivity map, D5 unfiltered `GET /workflows`, F4 browser-operator URLs. Unchanged.

## R5 — Not physical

Nothing in this note is a device, OAuth, or live Emergency Stop proof. That remains Stage 11.
