# Personal AI — W6 Governed Connectors Checkpoint

Date: 2026-09-14

## Validated history

- W6.1 governed connector foundation: implementation `baaa7da38956e97231970c548626a71cde257176`, validated integration `152ef13217b652121917a890de14e20edb139473`, documentation head `a828cca77bbb910306641fabcc0f8211e3e65e19`.
- W6.2 Drive/Sheets read-first: implementation `ecb5e2615d06816e869dd4adb398565bb5c524fa`, documentation head `6310709f65534dba79d89cccd8ea94c6a4c9d765`.
- W6.3 controlled Drive/Sheets writes: implementation `95d33a66dca6c9621e50dbbb8f7f3a5c35eb2254`, documentation head `28a4a12c8774103ce36eb0d6aeca285b875de8ff`, implementation tree `e879cee54f019ca2f98c8b90564fd2681bf5cab6`.
- Hosted Google OAuth qualification preparation: `f79958103c50c0e1b25442ffbf6e58e5b4e65203`, 6/6 required workflows PASS.
- Final Gmail Draft OAuth scope repair: `ae1b3c12ff82785b1f8cefe1bcbc6201e88b08bc`, full repository **446 PASS**, 6/6 required workflows PASS.

## Approved connector capability boundary

Drive writes enabled only for:
- `drive.files.create`
- `drive.files.upload`
- `drive.files.rename`
- `drive.files.update_content`

Sheets writes enabled only for:
- `sheets.spreadsheets.create`
- `sheets.values.update`
- `sheets.values.append`

Gmail operations remain individually scoped:
- read/search: `https://www.googleapis.com/auth/gmail.readonly`
- draft: `https://www.googleapis.com/auth/gmail.compose`
- send: `https://www.googleapis.com/auth/gmail.send`
- modify: `https://www.googleapis.com/auth/gmail.modify`

The prohibited Gmail full-access scope `https://mail.google.com/` is not added to runtime requestable scopes. Drive delete/trash/share/permission/ownership/arbitrary move and Sheets clear/delete/structural batchUpdate/sharing remain unavailable. No generic `google.write`, `gmail.full-access`, `drive.write`, or `sheets.write` permission exists.

## Gmail Draft defect repair

The raw Gmail operation contract already required `gmail.compose` for `gmail.draft`, but the live OAuth request surface did not expose that operation-required scope. Runtime manifest normalization now derives requestable optional scopes from every non-prohibited operation requirement. This admits `gmail.compose` while deliberately excluding scopes that exist only on prohibited operations. The Google provider catalog also includes the exact Gmail/Calendar/Drive/Sheets connector scope union.

The existing ConnectorGateway still enforces the operation's required scope before provider dispatch. Therefore Draft fails closed without `gmail.compose`, while read/search and send keep their independent least-privilege scopes. Google incremental authorization, cumulative confirmed-scope preservation, and reduced-scope detection remain unchanged.

Regression coverage proves:
- Draft permitted with `gmail.compose`;
- Draft rejected without `gmail.compose`;
- read/search unchanged;
- send unchanged;
- Calendar/Drive/Sheets scope union preserved;
- reduced/revoked provider scopes detected;
- OAuth/qualification evidence remains redacted.

## Exact-head automated evidence — Gmail scope repair

| Workflow | Run | Run ID | Conclusion |
| --- | ---: | ---: | --- |
| CI | #597 | `34854396694` | PASS |
| Reliability and Security | #164 | `34854396635` | PASS |
| P3 iPhone PWA | #132 | `34854396766` | PASS |
| Android Instrumentation | #163 | `34854396887` | PASS |
| Package Validation | #163 | `34854396651` | PASS |
| iOS Companion | #145 | `34854396843` | PASS |

CI passed dependency checks, repository compileall and full `pytest -q`: **446 passed, 7 warnings**. Package Validation passed Windows, macOS and Ubuntu.

## Hosted OAuth qualification preparation

The validated hosted-prep path provides:
- explicit `OAUTH_REDIRECT_URI` override;
- HTTPS callback route `/connector-oauth/callback`;
- public no-store/no-referrer callback shell;
- same-origin authenticated finalize route `/iphone/api/connectors/oauth/finalize`;
- durable OAuth state routing bound to owner/device/session/security epoch;
- PKCE single-use/replay/expiry handling;
- redacted real-provider evidence schema;
- harmless qualification resource naming.

Hosted runtime storage already fails closed unless `PERSONAL_AI_DATA_DIR` resolves beneath a proven non-root persistent mount under `PERSONAL_AI_DURABLE_ROOT` and a write/fsync/readback probe succeeds. Encrypted backup/restore uses the owner root-key architecture and SQLite-safe snapshots.

## Railway live-qualification checkpoint

An isolated service named `personal-ai-connector-qualification` was approved for creation, but Railway rejected provisioning before creation with `Free plan resource provision limit exceeded. Please upgrade to provision more resources.` No service, domain, volume, variable, or deployment was created. The owner subsequently chose not to upgrade Railway now.

Status is therefore:

**BLOCKED — OWNER-APPROVED PAID INFRASTRUCTURE DEFERRED**

This is not a W6 software failure. Preserve the continuation point:
- create a separate isolated connector-qualification service only after future owner approval of paid infrastructure;
- source from the validated W6 branch/head available at that time;
- attach a separate persistent `/data` volume;
- set `PERSONAL_AI_DURABLE_ROOT=/data` and `PERSONAL_AI_DATA_DIR=/data` or the explicitly approved mounted subdirectory;
- use a separate HTTPS domain and exact callback `https://<qualification-domain>/connector-oauth/callback`;
- add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` directly in Railway, never in chat;
- use a dedicated harmless Google qualification account first;
- retain real-provider evidence for identity/scopes/incremental consent/refresh/reconnect/revoke, Gmail/Calendar/Drive/Sheets operations, blocked destructive actions, restart persistence, backup and restore.

Do not reuse `personal-ai-iphone-qualification` and do not deploy W6 candidates to `personal-ai-runtime` production for this evidence lane.

## Classification and production boundary

W6 software is now:

**IMPLEMENTED**  
**INTEGRATED**  
**AUTOMATED VALIDATED**  
**LIVE OAUTH QUALIFICATION PENDING**  
**PRODUCTION QUALIFICATION PENDING**

No production deployment, Railway variable/storage/service/source-branch/volume change was made by this software closure. PR #22 remains draft/unmerged, and PR #18/#21 remain separate/unmerged.

## Exact independent continuation

Because hosted live qualification is deferred by an owner-approved paid-infrastructure decision, independent engineering continues with:
1. code-only W6 qualification/deployment artifacts and fail-closed configuration validation;
2. W7 Safe Computer Operator in bounded exact-head batches beginning with W7.1 Durable Operator Transaction Core;
3. W8/W9 and release hardening only after their preceding automated gates.

Live W6 operational qualification resumes from this checkpoint when the owner later enables isolated paid infrastructure and performs the required Google-account consent steps.
