# Personal AI — W6 Google Connector Live Qualification Runbook

Status: prepared only. Live execution is deferred until the owner unblocks paid isolated Railway infrastructure and supplies Google OAuth credentials directly to Railway.

## Source boundary

Use only a W6 software head that has passed all six required workflows. Do not deploy this runbook to `personal-ai-runtime` production and do not reuse `personal-ai-iphone-qualification`.

## Isolated service requirements

Service name: `personal-ai-connector-qualification`

Required runtime properties:

- separate Railway service/environment;
- separate HTTPS domain;
- separate persistent volume mounted at `/data`;
- `PERSONAL_AI_DATA_DIR=/data`;
- `PERSONAL_AI_DURABLE_ROOT=/data`;
- health check path `/health`;
- startup command `sh qualification/run_google_connector_qualification.sh`;
- no production owner data copied into the service;
- no production connector credentials reused;
- no P3 evidence files reused.

The startup wrapper runs the qualification preflight before importing the hosted app. Startup fails closed if secrets are missing, callback configuration is invalid, insecure PWA mode is enabled, or a durable `/data` mount cannot be proven.

## Exact environment-variable names

Secrets — owner enters these directly in Railway, never chat:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `PERSONAL_AI_ROOT_KEY`
- `PERSONAL_AI_IPHONE_ENROLLMENT_CODE`

Required non-secret values:

- `PERSONAL_AI_DATA_DIR=/data`
- `PERSONAL_AI_DURABLE_ROOT=/data`
- `OAUTH_REDIRECT_URI=https://<qualification-domain>/connector-oauth/callback`

Keep `PERSONAL_AI_IPHONE_ALLOW_INSECURE` unset/false.

## Callback and startup probes

The deployment is not ready until all of these are true:

1. `GET /health` returns HTTP 200.
2. `GET /connector-oauth/callback` exists and returns the no-store callback shell.
3. `POST /iphone/api/connectors/oauth/finalize` exists behind trusted browser/device authorization.
4. The preflight output reports durable storage state `ready`, mount point under `/data`, and configured flags only — never secret values.
5. Restarting the service does not change the persistent connector/approval/audit databases.

## Google test-account evidence template

Every retained test record must include only safe metadata:

- exact Git SHA;
- Railway deployment ID;
- environment/service name;
- redacted Google account identifier;
- connector;
- exact granted scopes;
- owner ID;
- trusted device ID;
- browser session ID;
- security epoch;
- operation ID;
- expected result;
- actual result;
- timestamp;
- redacted safe logs;
- retained artifact/evidence reference;
- pass/fail decision;
- evidence kind (`real_provider` or `simulated_provider`).

Never retain access tokens, refresh tokens, authorization codes, client secrets, PKCE verifiers, email/document contents, spreadsheet cell contents or passwords.

## Harmless qualification resources

Use only clearly named resources such as `Personal AI Connector Qualification <timestamp>`.

Drive: list/search, metadata/read/download, create a small text file, upload a small harmless text file, rename and update content, then verify through provider readback.

Sheets: create a qualification spreadsheet, read metadata/list worksheets/read a bounded range, update a small bounded RAW range, append a small row and verify readback. Formula-looking strings must remain literal data.

Do not enable delete, trash, sharing, permission, arbitrary move, clear or structural spreadsheet operations just to clean up qualification resources.

## Authentication qualification sequence

1. Start OAuth from a trusted owner browser/device/session.
2. Verify durable state, PKCE and exact callback.
3. Verify returned account identity and exact granted scopes.
4. Incrementally add Gmail, Calendar, Drive and Sheets scopes.
5. Prove previously confirmed scopes remain in the cumulative union.
6. Stop immediately if Google returns a reduced scope set unexpectedly.
7. Exercise token refresh and expiry recovery.
8. Exercise reconnect, local revoke and provider revoke.
9. Exercise session/device/security-epoch invalidation.
10. Verify state replay, duplicate callback and expired-state rejection.
11. Verify insufficient-scope rejection occurs before provider dispatch.

## Operational tests

Gmail: harmless read/search; Draft only with `gmail.compose`; sending remains approval-bound and must not target an external recipient without explicit owner approval.

Calendar: harmless read/search/create/update without external attendees.

Drive: reads plus approved create/upload/rename/content update, duplicate-operation protection and readback verification.

Sheets: reads plus bounded create/update/append using RAW values, duplicate protection and readback verification.

## Mandatory negative tests

Prove rejection before provider dispatch for Drive delete/trash/share/permission/ownership/arbitrary move, Sheets clear/delete/structural batchUpdate/sharing, automatic/background writes, writes without approval, writes without required reauthentication, writes from the wrong session/device and writes after Emergency Stop.

## Persistence and restart procedure

1. Complete one harmless connector operation and capture its operation ID.
2. Record connector health/scopes and the redacted evidence reference.
3. Restart/redeploy the isolated service.
4. Verify token metadata, connector state, operation ledger, Trusted Action state and audit records persist.
5. Verify no uncertain consequential action is redispatched after restart.
6. Verify the harmless provider resource remains retrievable.

## Encrypted backup/restore qualification

Use the repository `recovery.backup.BackupService` against `/data` with the same qualification root-key architecture.

Create an encrypted backup in the isolated service, inspect it, then restore it only into a separate isolated restore location/service. Run SQLite integrity checks and compare safe counts/IDs, not secret payloads. Never restore over the active qualification database while tests are running.

## Paid blocker

Current status: **BLOCKED — OWNER-APPROVED PAID INFRASTRUCTURE DEFERRED**.

Do not create the Railway service or accept a paid upgrade until the owner explicitly unblocks it. This blocker does not prevent W7/W8/W9 or other independent engineering.
