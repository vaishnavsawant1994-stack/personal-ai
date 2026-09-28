# External-dependency-free qualification — 2026-09-24

## Candidate

- Base branch: `v1/final-product-integration-20260916`
- Qualified software candidate SHA: `cb4bfb965fd0aa6632459aac6252833a94614150`
- Release version: `0.6.0`
- Qualification mode: local software, deterministic simulation, and mock-provider evidence

This checkpoint does not claim evidence from physical devices, paid hosting or
GPU resources, live provider consent, Apple signing, owner production keys, or
real microphones and desktops. Those items are deferred external evidence and
are not replaced by weaker production claims.

## Changes qualified

- Aligned Python, desktop packaging, Windows installer, Debian package, iOS,
  and Android product versions at `0.6.0`.
- Added a regression that prevents future version drift.
- Marked Google Drive MD5 comparison explicitly as a non-security provider
  checksum, eliminating the misleading high-severity scanner result without
  weakening content verification.
- Added secure-vault startup guidance for desktop, headless, and CI use.
- Added the canonical owner model-privacy preference and desktop control. The
  existing governed router now applies `local_only`, `local_preferred`, or
  `external_allowed` immediately and rejects invalid values without changing
  the last valid policy.
- Added manual CI dispatch configuration to PR #33 and the default branch.
- Added explicit identifier allowlists to the workflow, everyday-intelligence,
  personal-operations, and OAuth dynamic SQL boundaries. Malformed column/scope
  identifiers now fail closed before database access.

## Results

| Gate | Result | Evidence |
| --- | --- | --- |
| Focused release/Drive/iOS tests | PASS | 58 passed |
| Full Python test suite | PASS | 2,016 passed; 23 deprecation warnings |
| Python compilation | PASS | `compileall` completed |
| Installed dependency consistency | PASS | no broken requirements |
| Dependency vulnerability audit | PASS | no known vulnerabilities |
| Bandit high-severity scan | PASS | zero high-severity findings |
| Ruff | PARTIAL | new Stage-8 SQL guard regression file passes; repository-wide pre-existing lint backlog remains and touched legacy modules are not globally clean |
| Core/P7/P8 simulated soak | PASS | 4,362 iterations; all SQLite integrity checks `ok`; zero pending device requests; RSS growth 58,134,528 bytes |
| P9 governed-router soak | PASS | 754,822 iterations; privacy blocks, failover, circuit-open and recovery exercised; RSS growth 1,531,904 bytes |

## Deferred external evidence

| Evidence | Status | Substitute used now |
| --- | --- | --- |
| Physical iPhone and Android interaction | DEFERRED | automated mobile/PWA contracts and simulated devices |
| Paid Railway/GPU capacity | DEFERRED | local CPU runtime, mocks, and bounded soaks |
| Google/provider consent | DEFERRED | provider adapters and mocked OAuth/HTTP contracts |
| Apple Developer signing/TestFlight | DEFERRED | project and unsigned configuration validation |
| Owner production certificates/keys | DEFERRED | ephemeral test secrets and fail-closed startup validation |
| Real microphone, desktop, and devices | DEFERRED | synthetic audio and simulated platform adapters |

## Remaining release blockers

1. Repository CI must be restored at the GitHub account level. GitHub rejected
   manual dispatch with `Actions has been disabled for this user`; repository
   Actions permissions are enabled and the workflows now expose manual dispatch.
2. PR #33 must remain draft until the wider Stage-8 authority/injection audit is
   formally closed and the exact new head is qualified.
3. Production readiness must not claim the deferred external evidence above.
4. Repository governance still needs required branch protection, dependency
   alerts, code scanning, a security policy, and private vulnerability reporting.

## Decision

The exact branch candidate is locally software-qualified for this closure
slice. It is not yet a production release candidate: account-level GitHub
Actions and the remaining Stage-8 audit must close before merge.
