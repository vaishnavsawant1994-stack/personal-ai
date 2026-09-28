# Personal AI Owner Product Operations

## Implemented product surfaces

- `/iphone/` provides persistent conversations, hands-free browser voice, interruption, approvals, Memory, Knowledge, Activities, workflows, qualification status and trusted-device management.
- Personal memory and uploaded knowledge are separate durable stores. Retrieved answers label memory separately from document citations.
- Workflows retain checkpoints in SQLite, fail closed after a restart, and require owner-directed resumption. Consequential tool calls still enter the one-use approval system.
- Existing owner-enrolled iPhone browsers retain their trusted cookies and receive the owner scope migration without re-enrollment. Each newer device has an independent scope set and can be revoked immediately.
- Model routing is provider-neutral and records provider selection/fallback. Temporary Gemini remains usable while the private endpoint is unavailable.

## Owner-facing data controls

- Memory: inspect retrieval score/history/relationships/conflicts; correct; permanently delete; export; apply retention; classify sensitive/secret.
- Knowledge: upload TXT, Markdown, CSV, JSON, PDF, DOCX or XLSX (10 MB maximum); index; search; inspect source chunks and citations; update metadata/access; delete; export.
- Devices: list, inspect last use/scopes, change permissions, and revoke a lost device.
- Activities: inspect model, action, approval, workflow, device and qualification audit events.

## Owner sign-in

The enrollment code remains a first-device and emergency bootstrap path. A trusted owner can additionally create a Face ID/passkey, an owner password and one-time recovery codes in **Settings → Security**.

Google owner sign-in requires both `GOOGLE_SIGNIN_CLIENT_ID` and `PERSONAL_AI_OWNER_GOOGLE_EMAIL`. Create a Google Identity Services Web client whose authorized JavaScript origin is the exact Personal AI HTTPS origin. The server verifies the Google ID-token signature, audience, expiry, subject, verified-email claim and exact configured owner email before issuing the same scoped HttpOnly trusted-device cookies. Other Google accounts fail closed. A Google client secret is not required for this authentication-only ID-token flow.

## Connector configuration

Gmail, Google Calendar, Slack and Home Assistant tools are registered only when their approved adapters are configured. Read operations are read-only. Sending, creating, updating or device-control calls require policy approval; deletion is destructive. Provider/account credentials belong in the encrypted vault or deployment environment and must never be committed.

## Self-hosted inference

The ready-to-deploy vLLM package is in `deploy/self-hosted-model/`. On an owner-purchased NVIDIA GPU host:

1. Copy its `.env.example` to `.env` and supply a random gateway bearer token and selected model ID.
2. Start the Compose stack and run `verify.sh`.
3. Configure Railway `LOCAL_AI_URL=https://<private-model-host>/v1`, `LOCAL_AI_KEY=<gateway-token>`, `LOCAL_AI_MODEL=<model-id>`, `AI_PROVIDER=local`, and `MODEL_LOCAL_FIRST=true`.
4. Verify `/iphone/api/system/status`, a normal turn, a model-timeout trial and the recorded fallback audit before removing Gemini fallback.

The GPU deployment is not claimed complete until a host is purchased and the live health/latency/privacy checks pass.

## Qualification boundary

Automated tests validate the recorder and owner interfaces but do not count as physical evidence. PR #18 must remain unmerged until the exact `78c7e9d6d848f0dcc93ee4f1f281fad4eff970f5` deployment has retained mandatory P3 real-device/production-like evidence. P3.2–P3.8 cannot be self-awarded by the model.
