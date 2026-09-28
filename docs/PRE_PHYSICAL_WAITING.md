# Pre-physical waiting note

**Last exact-head 6/6 software candidate:** `08b2616c11d1433760eb711db4ca7f82e5a01a2c`  
**This file is not that SHA and is not a Stage 11 freeze.**

No Stage 11 row is `PASS`. Stage 12 is not open. The public p2 site is not a qualification host. A virtual phone is not a physical pass.

## Software audit

The 15 procedure sections, the collector, the identity route, the fail-closed storage gate, and enrollment were reviewed with the existing tests. Enrollment still requires HTTPS unless insecure mode is explicitly enabled, and it rejects a missing or short code. The identity payload stays `production: false` and `rows_passed: 0`. A simulated, emulated, or GitHub-hosted packet is still rejected.

One defect was closed. After a connector was revoked, a live adapter could still present its token, and a successful provider call or health check could mark that connector healthy again. Revoke now drops the live token. A revoked or revocation-pending connector is not called and is not returned to healthy. This commit is not a qualified SHA until its own exact-head 6/6. Until then the software candidate remains `08b2616c11d1433760eb711db4ca7f82e5a01a2c`.

Server-side Emergency Stop persistence, OAuth vault storage, and backup skip of the nine security stores stay covered by earlier tests. They are not `S11-ESTOP-01`, `S11-OAUTH-01`, or `S11-FAIL-06`. A real provider login was not performed.

## Still blocked

| Gate | State |
|---|---|
| Durable qualification disk | Not attached |
| Stable HTTPS qualification hostname | Not created |
| Model credential in a secret store | Not configured |
| New enrollment code | Not issued |
| Real provider login | Not done |
| Physical iPhone, Android, microphone, and second device | Not available |

`ready_for_physical` is not claimed.

## When hardware exists

Run `S11-IOS-01` first on the deployed SHA. Then voice, network, background, stale session, revocation, and microphone permission. OAuth and external revoke stay owner-gated. Emergency Stop on that host is separate from the old server-side tests. Android and two-device handoff wait for a second physical device. A failure is repaired, re-qualified at a new exact SHA, redeployed, and rerun. Stage 11 freezes only at 15 real passes. Stage 12 opens only after that freeze.
