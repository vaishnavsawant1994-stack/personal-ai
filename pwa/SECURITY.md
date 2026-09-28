# iPhone PWA Security Boundaries

- Owner enrollment is HTTPS-only unless an explicit local-test override is enabled.
- Enrollment compares the configured owner code with `hmac.compare_digest`.
- The server creates the trusted device credential; the credential is never exposed to JavaScript.
- Device id and token are stored in Secure, HttpOnly, SameSite=Strict cookies scoped to `/iphone`.
- Every protected endpoint re-authenticates the trusted device and rejects revoked devices.
- Model/provider credentials remain server-side.
- The service worker does not cache `/iphone/api/` responses.
- P3 evidence remains server-side in the existing qualification database.
- Browser or CI execution does not self-award physical-device qualification.
