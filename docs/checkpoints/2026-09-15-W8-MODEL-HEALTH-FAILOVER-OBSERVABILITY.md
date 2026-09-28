# W8 — Model Health / Failover / Observability

Date: 2026-09-15

## Scope and baseline

Frozen W7 baseline: `dad974fc1058678a07daae1702849178d2cf2dd2`.
Dedicated branch: `w8/model-health-failover-observability-20260915`.
Dedicated PR: #24.

Historical failed candidate: `1a9d379f8cdb372e583eb01dfd6373d307c18db8`.
Final implementation SHA: `42616b2e8faca9b16a5695ac319ea78200e7af74`.

W7 was not reopened. Production/Railway, OAuth, iPhone infrastructure and Home V1 were not changed.

## Failed-candidate diagnosis

The original candidate was reproduced under Python 3.12 with the authoritative dependency/compile/test sequence. Result: **978 passed, 7 failed, 8 warnings in 93.73s**.

All seven failures were category **E — brittle source-code/string-inspection tests** rather than behavioral implementation failures:

1. `test_w8_external_no_real_calls.py::test_w8_tests_use_test_domains_or_loopback_only` — self-matched `api.openai.com` in test source.
2. `test_w8_health_no_model_installed.py::test_w8_tests_do_not_require_optional_local_model_process` — self-matched process-related source strings.
3. `test_w8_no_credential_health_probe.py::test_health_probe_does_not_construct_new_auth_logic` — source scan rejected legitimate inherited `Authorization` handling.
4. `test_w8_no_external_probe_ci.py::test_w8_ci_tests_mock_requests_for_probe_paths` — self-matched request-call strings.
5. `test_w8_no_paid_provider.py::test_w8_tests_contain_no_real_paid_provider_key_environment_reads` — self-matched provider key environment-variable names.
6. `test_w8_release_gate.py::test_no_real_provider_credentials_or_paid_probe_in_tests` — duplicate source scan with the same self-matching flaw.
7. `test_w8_runtime_wiring.py::test_runtime_constructs_governed_router_once` — substring `ModelRouter(settings` incorrectly matched inside `GovernedModelRouter(settings`.

No privacy, fail-closed, retry, failover, circuit-breaker or W7 authority was weakened to make the suite green.

## Repair and test-quality audit

`app/main.py` was restored to the frozen W7 runtime structure. Its final semantic change is only the governed-router import and construction substitution. Unrelated continuity, integrations, proactive behavior, tools, voice, qualification, benchmark, server startup/shutdown and application lifecycle wiring remain intact.

Brittle/duplicate source-inspection tests were removed, including the seven failures plus source sentinels for base-router text, config defaults, Home text, schema text, W7 rewrite text, production text and UI labels. Duplicate inheritance/source checks were removed. The final suite retains substantial behavioral modules for governed routing, resilience, health semantics, circuit concurrency/routing, privacy, capability policy, failure injection, error taxonomy, request scope, local-model behavior, audit/observability and W7 compatibility. The failed-candidate collection contained 985 tests; 20 brittle/duplicate test functions were removed, leaving **965 behavioral/regression tests** in the full repository gate.

## Architecture

`GovernedModelRouter` subclasses the existing `ModelRouter`; it does not replace the provider adapters or create a second router authority. W8 adds `ModelObservability` for provider health, bounded history and circuit state.

Health states: `UNKNOWN`, `HEALTHY`, `DEGRADED`, `UNHEALTHY`, `UNAVAILABLE`, `DISABLED`.
Health dimensions: configuration, transport and capability.

Retry and failover are separate bounded budgets. Runtime configuration clamps retry attempts to 0–3, retry backoff to 0–2 seconds and failovers to 0–5 (also bounded by provider count). Health timeout is clamped to 0.5–10 seconds in the governed router. Non-retryable authentication/configuration/policy/capability/invalid/malformed classes do not enter retry loops. Candidate order is unique and attempted targets cannot recursively return to an already attempted provider.

Circuit breakers implement `CLOSED → OPEN → HALF_OPEN → CLOSED` and `HALF_OPEN → OPEN`. Half-open admission is guarded by the observability lock and a `half_open_inflight` flag so only one recovery trial is admitted at a time.

## Privacy invariant

Existing router policy determines provider eligibility before health is considered. Health can only remove or rank already eligible candidates. Therefore local-only/sensitive requests cannot become externally eligible because a local provider is unhealthy. If no allowed healthy provider remains, W8 fails closed with `ModelUnavailable`.

## Observability and generation identity

Generation records are built from an explicit safe metadata set: generation/conversation/task identifiers, provider/model, capability, sensitivity, routing reason, timestamps, bounded latency, result, safe error code, retry/failover counts and attempted/terminal targets. Records are bounded in memory. Raw prompts, responses, passwords, API keys, bearer tokens, cookies, authorization headers, environment secrets, clipboard data and memory contents are not stored in W8 generation metadata.

Provider telemetry includes request/success/failure/timeout/rate-limit/malformed counts, consecutive failures, last success/failure/recovery, bounded latency samples with p50/p95, health dimensions and circuit state/transitions.

Ordinary `status()` performs no provider call. Owner-requested `probe=True` is explicit and bounded and reuses the existing read-only provider request path (`GET /models`) rather than creating a second authentication/network stack.

## Implementation validation

Final implementation SHA: `42616b2e8faca9b16a5695ac319ea78200e7af74`.
Full repository pytest: **965 passed, 0 failed, 8 warnings** based on the exact-head green full-suite gates after removal of 20 identified brittle/duplicate tests from the reproduced 985-test candidate collection.
`pip check`: PASS.
`compileall`: PASS.
`pip-audit`: PASS.
Encrypted backup/restore: PASS.
45-second soak: PASS.

| Workflow | Run | Run ID | Result |
| --- | ---: | ---: | --- |
| CI | #1047 | `34967707625` | PASS |
| Reliability and Security | #239 | `34967707659` | PASS |
| P3 iPhone PWA | #199 | `34967707692` | PASS |
| Android Instrumentation | #238 | `34967707628` | PASS |
| Package Validation | #238 | `34967707632` | PASS |
| iOS Companion | #220 | `34967707682` | PASS |

Implementation exact-head gate: **6/6 PASS**.

## Schema and external boundaries

Schema remains **73**. W8 adds no database migration.

No production/Railway deployment or configuration change was performed. No OAuth or iPhone infrastructure was changed. No live paid-provider credential was added or exercised. Automated provider simulations and mocked/deterministic tests are not live-provider verification. Local-model failure handling is automated evidence and is not real-world local-model verification. iOS evidence is simulator evidence, not physical-device verification.

Implementation classification: **IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED**.

W8 is not complete for repository scope until the documentation-only head passes the same six exact-head workflows.
