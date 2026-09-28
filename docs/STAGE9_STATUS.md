# Stage 9 status — not exited

**Entered:** after Stage 8 freeze `b17c5051772b5e82b7a6a208903bb0300bf1e405`.  
**Date:** 28 September 2026  
**Exit:** **No.** Stage 10 is not open. Stages 11 and 12 are not started.

## Work packages

| WP | State | Evidence |
| --- | --- | --- |
| WP0 Branch hygiene | Done for the freeze SHA | Control API intact. 6/6 on `b17c505`. See `docs/STAGE8_FREEZE.md`. |
| WP1 Authority map | Map already in `docs/STAGE9_THREAT_MODEL_AND_PLAN.md`. Single-definition lint added. | `tests/test_stage9_single_writers.py` |
| WP2 Entrypoint census | Inventory complete. Per-route authority audit is not. | `docs/stage9_entrypoint_census.json` (191 decorators). One control-plane gap remains: `GET /workflows` (D5, deferred). Seven legacy PWA routes are stripped when `include_legacy_runtime_routes=False`. |
| WP3 Composition harness | H1–H12 automated on this branch. Not yet exact-head CI. | `tests/test_stage9_composition.py` |
| WP4 Consent matrix | Not started | |
| WP5 Migration kit | Not started. No schema change in this pass. | |
| WP6 Audit schema freeze | Not a new schema. G2 behavior is Stage 8 CLOSED; no second activity schema. | |
| WP7 Stage 9 freeze | **Not done** | Exit criteria 3 and 4 are not met as a frozen SHA. 150 routes are `inventoried`, not individually classified. |

## Explicit non-claims

- Residual routes were **not** deleted in this pass. Deleting them without a parity proof would add risk.
- Companion minimum versions are not set. That is Stage 11 (owner devices).
- F4 browser-operator URLs are not closed.
- No merge. No production-ready claim.

## Next legal step

Exact-head 6/6 on the commit that contains the Stage 9 tests. That re-proves the freeze code plus the new tests. It does **not** by itself exit Stage 9, and it does not open Stage 10.
