# Personal AI V12 — Secure Cloud Runtime & Web Companion

V12 introduces a fail-closed internet boundary for the Personal AI web companion without publishing privileged local credentials.

## Security model

- Cloud runtime is disabled by default.
- Enabling it requires `PERSONAL_AI_CLOUD_OWNER_SECRET` with at least 32 characters and an explicit `CLOUD_ALLOWED_ORIGINS` allow-list.
- Wildcard CORS is rejected.
- Existing device pairing remains one-use and owner-initiated: `/pair/start` is loopback-only; the resulting token/code can be entered on the web companion and consumed once at `/pair/confirm`.
- Long-lived device bearer credentials are kept only in browser `sessionStorage`, never in the repository or `localStorage`.
- The browser exchanges the device credential for a short-lived opaque cloud session. Only the SHA-256 token digest is persisted by the runtime.
- Session scopes are least-privilege by default: chat, status, normal memory read, and approval read/write.
- Mutating cloud calls use high-entropy one-time nonces and reject replay.
- Per-session sliding-window rate limiting is enforced.
- Sensitive memories are filtered unless a future session is explicitly issued `memory:sensitive`.
- Consequential tools continue to use the existing exact-execution one-use approval flow.
- Emergency stop is owner-secret protected and blocks command/tool approval execution while active.
- Session revocation and device revocation remain independent controls.
- Web companion code contains no AI provider keys, cloud owner secret, local device secrets, Apple keys, or private runtime credentials.

## Required runtime configuration

```text
CONTROL_SERVER_ENABLED=true
CLOUD_RUNTIME_ENABLED=true
PERSONAL_AI_CLOUD_OWNER_SECRET=<random >=32 character secret>
CLOUD_ALLOWED_ORIGINS=https://personal-ai-fawn.vercel.app
CLOUD_SESSION_TTL_SECONDS=900
```

The cloud-facing control service must be terminated behind HTTPS. Do not expose an unencrypted `http://` control server to the public internet.

## Pairing flow

1. The trusted owner runtime creates a pairing offer locally using `/pair/start`.
2. The user enters the pairing token and code in the web companion.
3. `/pair/confirm` consumes the one-use offer and enrolls the iPhone web companion.
4. The web client exchanges the device bearer for a short-lived `/cloud/session` token.
5. The short-lived session is used for `/cloud/command`, `/cloud/status`, `/cloud/memory/search`, and `/cloud/approval`.
6. Browser close clears session-only credentials; the device can also be revoked at the runtime.

## Production gate

V12 software is not production-complete until the HTTPS runtime/relay is deployed, the Vercel origin is allow-listed, an iPhone is paired through a real one-use offer, authenticated chat/memory/approval/status round trips succeed, emergency stop is exercised, revocation is verified, and the exact candidate passes CI/security validation.
