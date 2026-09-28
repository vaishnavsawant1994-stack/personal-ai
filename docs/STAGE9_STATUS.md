# Stage 9 status — not frozen

**Entered:** after Stage 8 freeze `b17c5051772b5e82b7a6a208903bb0300bf1e405`.  
**Qualified checkpoints:** `0024a2b` and `560937f`, both exact-head 6/6.  
**Exit:** **No.** This file is not a freeze. Stage 10 is not open. Stages 11 and 12 are not started.

## What is recorded

| Item | State |
| --- | --- |
| 191 routes | Classified in `docs/stage9_route_classification.json`. None remain `inventoried`. |
| Legacy seven | `legacy-opt-in`. Router default is False. Production passes False. |
| Emergency Stop | Tool registry `runtime-controls.sqlite3` is the durable flag. A fresh cloud session mirror does not clear it. Restart keeps the stop. Official cloud write updates both and fails if they diverge. |
| Consent matrix | `docs/STAGE9_CONSENT_MATRIX.md`, generated from the classification. Web companion calls only the cloud rows. |
| Composition | H1–H12 remain. Restart and mirror-cannot-clear tests are in `tests/test_stage9_emergency_stop_authority.py`. |

## Deferred gaps (recorded, not closed)

1. `GET /workflows` — D5. Authenticated, list projection still deferred.
2. `GET /capabilities/api/status` — no session check. Presence only.
3. `POST /iphone/api/logout` — clears cookies. Does not revoke the device or server session.

C6 and F4 stay deferred from Stage 8. Physical proof stays Stage 11.

## Still required before a Stage 9 freeze

Exact-head 6/6 on the commit that contains this classification. `560937f` does not cover it. Do not merge. Do not open Stage 10.
