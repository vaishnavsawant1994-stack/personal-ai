# Personal AI — W6 Gmail Scope Repair & Deferred Live Qualification

Date: 2026-09-14

## Baseline

- Qualification-prep baseline: `f79958103c50c0e1b25442ffbf6e58e5b4e65203`.
- Gmail scope repair exact implementation head: `ae1b3c12ff82785b1f8cefe1bcbc6201e88b08bc`.
- PR #22 remains draft/open/unmerged.
- Production and the existing iPhone qualification service remain unchanged.

## Gmail Draft scope repair

`gmail.draft` continues to require `https://www.googleapis.com/auth/gmail.compose`.

The runtime now derives the effective requestable OAuth scope set from required/optional manifest scopes plus the required scopes of non-prohibited operations. This makes `gmail.compose` requestable for Draft while excluding the prohibited Gmail full-access delete scope `https://mail.google.com/`.

The Google provider catalog includes Gmail read, compose, send and modify scopes plus the existing Calendar, Drive and Sheets scopes. Gmail read/search and send remain independently governed by their prior least-privilege scopes. The provider-level OAuth manager continues to preserve cumulative confirmed Google scopes and detect reduced scope sets.

## Regression coverage

The focused regression suite proves:

- Draft is permitted only with `gmail.compose`.
- Draft is rejected without `gmail.compose` before provider dispatch.
- Gmail read/search remain on `gmail.readonly`.
- Gmail send remains on `gmail.send`.
- Calendar, Drive and Sheets scope union remains available.
- Reduced/revoked scope detection remains fail-closed.
- Qualification evidence continues to redact account identifiers and token/code fields.

## Exact-head automated evidence

All six required workflows passed on `ae1b3c12ff82785b1f8cefe1bcbc6201e88b08bc`:

- CI #597 / `34854396694` — PASS
- Reliability and Security #164 / `34854396635` — PASS
- P3 iPhone PWA #132 / `34854396766` — PASS
- Android Instrumentation #163 / `34854396887` — PASS
- Package Validation #163 / `34854396651` — PASS
- iOS Companion #145 / `34854396843` — PASS

## Live qualification blocker

Creation of `personal-ai-connector-qualification` and its dedicated `/data` volume is recorded as:

**BLOCKED — OWNER-APPROVED PAID INFRASTRUCTURE DEFERRED**

Railway refused a third service on the current Free plan because the resource provision limit is exceeded. The owner explicitly postponed the paid Hobby upgrade. This is a deferred infrastructure gate, not a W6 software failure.

Future continuation is preserved: create the isolated service only after owner payment approval, attach `/data`, use `PERSONAL_AI_DATA_DIR=/data` and `PERSONAL_AI_DURABLE_ROOT=/data`, generate a separate HTTPS domain, set `OAUTH_REDIRECT_URI=https://<qualification-domain>/connector-oauth/callback`, add Google connector credentials directly in Railway, use a dedicated qualification Google account, and retain redacted live-provider evidence.

## Final W6 software classification

- IMPLEMENTED
- INTEGRATED
- AUTOMATED VALIDATED
- LIVE OAUTH QUALIFICATION PENDING
- PRODUCTION QUALIFICATION PENDING

Do not call W6 operationally complete until real Google-provider and persistent-volume evidence exists.
