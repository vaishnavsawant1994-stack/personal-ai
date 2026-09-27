# Personal AI V5 — Production Hardening

V5 upgrades V4 with interruptible full-duplex voice, OAuth PKCE + refresh lifecycle, OS-keychain-protected vault root keys, transactional desktop actions, persistent Android background device execution, request/response device commands, authenticated visual dashboard, signed release manifests, native installer packaging, emulator instrumentation, dependency auditing, and soak testing.

Security invariants: bearer credentials stay in headers; pairing and OAuth initiation/callback are loopback-only; refresh tokens live in the encrypted vault; the vault master key defaults to the OS keychain; external/destructive integration effects remain explicit; device command responses are correlated by random request IDs; release manifests are Ed25519 signed and packages are SHA-256 verified; desktop rollback is best-effort and action verification is recorded rather than assumed.

Production release requires configuring the GitHub repository secret `PERSONAL_AI_RELEASE_PRIVATE_KEY_B64` and publishing the corresponding public key to `RELEASE_PUBLIC_KEY_B64`. Hardware real-device testing can use the same Gradle instrumentation suite on an attached/self-hosted Android runner; GitHub-hosted CI validates it on an API-35 emulator.
