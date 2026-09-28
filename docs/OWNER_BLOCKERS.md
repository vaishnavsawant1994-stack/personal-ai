# Personal AI — Owner Blockers

Baseline date: 2026-09-14

Only genuine external/owner-only dependencies belong here. Work on independent tasks continues while these remain unresolved.

## BLOCKER-001 — Physical P3 qualification

- Workstream: W3 / W12
- Status: BLOCKED_OWNER
- Description: mandatory P3 real-device/production-like qualification remains incomplete for PR #18 exact candidate.
- Why owner involvement is required: the protocol requires physical-device evidence and must not be fabricated or substituted with simulator/browser automation.
- Exact owner action: when requested at the qualification stage, operate/authorize the required physical iPhone/browser/device tests and provide any device interaction that cannot be automated legitimately.
- Date discovered/confirmed: 2026-09-14
- Branch/SHA: `qualification/p3-iphone-first-20260908` / `78c7e9d6d848f0dcc93ee4f1f281fad4eff970f5`
- Work that can continue meanwhile: W1 storage, W2 security hardening, tests, connector mocks, workflows, observability, packaging preparation.
- Resolution: OPEN

## BLOCKER-002 — Main Railway durable storage infrastructure if billable/creation approval is required

- Workstream: W1
- Status: BLOCKED_OWNER_CONDITIONAL
- Description: the production `personal-ai-runtime` service currently has no persistent Railway volume. The connected Railway API can inspect mounts but does not expose a volume-creation action in the current tool surface.
- Why owner involvement is required: creating/attaching storage may require a dashboard/CLI action and can create billable infrastructure; the completion directive treats paid purchases as owner-only.
- Exact owner action: only if the coordinator cannot attach an already-included/non-billable persistent volume through authorized tooling, approve/create a Railway persistent volume for the main runtime and mount it at `/data` (or approve equivalent PostgreSQL infrastructure if selected after concurrency review). Do not paste credentials into chat.
- Date discovered/confirmed: 2026-09-14
- Branch/SHA: deployed `ui/personal-ai-cosmic-home-20260912` / `e63f02b653dd821ebe41cb7100dadd1b99f0af53`
- Work that can continue meanwhile: implement fail-closed storage validation, diagnostics, tests, backup/restore tooling and deployment config preparation.
- Resolution: OPEN

## BLOCKER-003 — GPU host purchase for private/self-hosted inference

- Workstream: W8
- Status: BLOCKED_OWNER
- Description: vLLM deployment package exists but no live GPU endpoint is proven.
- Why owner involvement is required: GPU hosting purchase/payment is external and potentially billable.
- Exact owner action: purchase/approve the selected GPU host when ready. Do not send provider passwords/API keys in chat; install secrets directly in the target service.
- Date discovered/confirmed: 2026-09-14
- Branch/SHA: PR #21 `a8a6d61be84747076a04360bf6f46defbeb7a664`
- Work that can continue meanwhile: harden provider abstraction, privacy routing, health/failure tests and deployment package.
- Resolution: OPEN

## BLOCKER-004 — Third-party OAuth consent

- Workstream: W6
- Status: BLOCKED_OWNER_WHEN_LIVE_QUALIFICATION_REACHED
- Description: live Gmail/Calendar/Drive/Sheets/Microsoft-style connector qualification requires the owner's provider consent and credentials/scopes.
- Why owner involvement is required: OAuth consent cannot be self-granted by Personal AI.
- Exact owner action: complete the provider's OAuth consent screen when the coordinator reaches live connector qualification. Do not paste client secrets/tokens into chat; add them through the provider/deployment secret interface.
- Date discovered/confirmed: 2026-09-14
- Branch/SHA: continuation branch from PR #21
- Work that can continue meanwhile: connector interface, mocks, read-only operations, risk/approval tests.
- Resolution: OPEN

## BLOCKER-005 — Apple Developer account / iOS distribution signing

- Workstream: W10 / W12
- Status: BLOCKED_OWNER
- Description: native TestFlight/App Store distribution cannot be completed without Apple Developer membership/signing prerequisites.
- Why owner involvement is required: account enrollment, agreements, certificates and distribution permissions are external legal/account actions.
- Exact owner action: provide/authorize Apple Developer distribution prerequisites when native iOS distribution is ready for qualification. Do not paste private signing keys into chat.
- Date discovered/confirmed: 2026-09-14
- Branch/SHA: current iOS project on PR #21/deployed UI lineage
- Work that can continue meanwhile: PWA-first iOS, native project maintenance, unsigned build/test preparation.
- Resolution: OPEN

## BLOCKER-006 — Permanent domain purchase

- Workstream: W10
- Status: BLOCKED_OWNER
- Description: permanent `ai.<domain>` migration cannot be executed until a domain is owned.
- Why owner involvement is required: domain purchase/payment and registrar ownership are external actions.
- Exact owner action: purchase/approve the permanent domain when ready; then provide the domain name (not registrar password) so Railway DNS/SSL/OAuth/PWA/cookie migration can be performed.
- Date discovered/confirmed: 2026-09-14
- Branch/SHA: infrastructure-level
- Work that can continue meanwhile: keep Railway domain operational, prepare migration checklist/config.
- Resolution: OPEN

## BLOCKER-007 — Windows/Android production signing material if required

- Workstream: W10 / W12
- Status: BLOCKED_OWNER_WHEN_RELEASE_SIGNING_REACHED
- Description: production-signed installers/packages require owner-controlled signing identities/keys/certificates.
- Why owner involvement is required: signing identities are sensitive credentials and may require external purchase/registration.
- Exact owner action: install signing material directly into the approved CI/secret store when requested; never paste private keys/passwords into chat.
- Date discovered/confirmed: 2026-09-14
- Branch/SHA: current packaging/client branches
- Work that can continue meanwhile: unsigned/dev package validation, installer/update logic, physical test preparation.
- Resolution: OPEN
