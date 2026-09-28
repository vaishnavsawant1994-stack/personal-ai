# Personal AI — Current Product Baseline

Generated: 2026-09-14

This file is the authoritative continuation checkpoint for the continuous product-completion workstream. It records evidence observed before making product/runtime changes.

## Repository truth

Repository: `sawantvaishnav1994-ai/personal-ai`

| Ref | Current state | Exact SHA | Promotion rule |
| --- | --- | --- | --- |
| `main` | unmodified release baseline | `b28dca539081a963ff987ebd94153e065f17d78e` | keep releasable |
| PR #18 / `qualification/p3-iphone-first-20260908` | open, draft, unmerged | `78c7e9d6d848f0dcc93ee4f1f281fad4eff970f5` | do not merge until mandatory physical P3 evidence passes on this exact candidate |
| PR #19 / `future/p4-p10-integrated-20260908` | open, draft, stacked on P3 | `0cae827dec4a23adefe1acf5e5f9683c2056aa74` | do not promote blindly |
| PR #21 / `completion/p3-p10-product-20260912` | open, draft, stacked on P3 | `a8a6d61be84747076a04360bf6f46defbeb7a664` | remains unmerged until P3/dependency/release gates pass |
| Railway source branch `ui/personal-ai-cosmic-home-20260912` | deployed production source; diverged from PR #21 | `e63f02b653dd821ebe41cb7100dadd1b99f0af53` | production changes require coordinator review and exact-head verification |
| Continuation branch `completion/continuous-product-20260914` | created from PR #21 head | starts at `a8a6d61be84747076a04360bf6f46defbeb7a664` | all new completion work lands here until explicitly integrated |

The deployed UI branch and PR #21 are **diverged**, not identical. Their merge base is `ff46d08ba70a4aafa151b55ba2465df4af249c9f`; the deployed branch is 11 commits ahead of that base while PR #21 is 3 commits ahead of it. Do not treat either branch as a drop-in replacement for the other.

## Exact-head CI evidence

PR #21 head `a8a6d61be84747076a04360bf6f46defbeb7a664` currently has successful GitHub workflow runs for:

- CI
- P3 iPhone PWA
- Android Companion
- Android Instrumentation
- iOS Companion
- Package Validation
- Reliability and Security

The deployed UI head `e63f02b653dd821ebe41cb7100dadd1b99f0af53` also has successful runs for the same seven workflow families.

Automated success is implementation evidence only. It does not satisfy physical P3 qualification.

## Railway truth

Project: `personal-ai-runtime`

Environment: `production`

### Service: `personal-ai-runtime`

- Service ID: `c2dacbf5-b118-4ea1-89a3-ea8868b374c4`
- Source branch: `ui/personal-ai-cosmic-home-20260912`
- Latest successful deployment: `8954a483-c1c2-486e-b345-286e95fa2a2f`
- Deployment commit: `e63f02b653dd821ebe41cb7100dadd1b99f0af53`
- Public domain: `personal-ai-runtime-production.up.railway.app`
- Healthcheck: `/health`
- Latest observed runtime log: service started successfully and `/health` returned 200; `/iphone/` also returned 200.
- **Persistent Railway volumes attached: none.**

This is a release blocker for durable owner data. The current application defaults `PERSONAL_AI_DATA_DIR` to `~/.personal_ai`; without an attached volume, production SQLite databases, knowledge objects, preferences, audit state and related files are not guaranteed to survive a redeploy/replacement container.

### Service: `personal-ai-iphone-qualification`

- Service ID: `7c6395df-7e09-491e-b514-4b3b609383b0`
- Source branch: `qualification/p3-iphone-first-20260908`
- Latest successful deployment: `5567d2d3-9ff3-4e98-90f9-8482d7a3e049`
- Persistent volume: `personal-ai-data`, mounted at `/data`, 500 MB
- Start command links `/root/.personal_ai` to `/data/.personal_ai` before starting Uvicorn.

The qualification service therefore has durable storage plumbing that the main runtime currently lacks.

## Current persistence implementation

`core/config.py` centralizes the data root at `PERSONAL_AI_DATA_DIR` (default `~/.personal_ai`). `app/main.py` places the following durable stores beneath that root:

- `assistant.sqlite3` — conversation messages, memory, relations, tasks and audit
- `vectors.sqlite3` — vector memory data
- `knowledge.sqlite3` and `knowledge/objects/` — owner knowledge metadata/chunks and uploaded objects
- `devices.sqlite3` — trusted devices/scopes
- `owner-access.sqlite3` — owner password/recovery/passkey state
- `continuity.sqlite3` — conversation/device continuity
- `proactive.sqlite3` — proactive state
- `automations.sqlite3` — automations/workflows
- `voice-qualification.sqlite3`
- `p3-qualification.sqlite3`
- `runtime-controls.sqlite3`
- `capability-benchmark.sqlite3`
- `model-dialogue-evaluation.sqlite3`
- JSON/file state including telemetry, preferences, vault and plugin data
- future-intelligence state under `future-intelligence/`

The code is largely persistence-capable, but production durability is **QUALIFICATION/BLOCKED** until the main Railway runtime uses durable storage and restart/redeploy/backup/restore evidence is recorded.

## Security baseline finding

The current executor has a one-use approval ticket bound to execution ID, tool name and exact parameter hash. That is useful groundwork, but the approval manager and paused execution state are process-memory only. The current ticket does not yet bind all mandatory fields from the completion directive (owner ID, device ID, session ID, security epoch, destination, data classification, expiry/use state persisted atomically). Therefore Trusted Action Core status is **PARTIAL**, not COMPLETE.

## Model baseline

The Railway connection exposes model-related variable names (`AI_PROVIDER`, `GEMINI_MODEL`, `GEMINI_API_KEY`, `MODEL_EVALUATION_ON_STARTUP`) but intentionally redacts their values through the connected Railway API. The last validated deployment commits are explicitly Gemini evaluation commits and the owner checkpoint says temporary Gemini is `gemini-3.5-flash-lite`; this remains a checkpoint, not a newly exposed secret/config value. No self-hosted GPU endpoint is claimed live.

## Immediate continuation

1. Add fail-closed hosted-storage validation and durable-storage diagnostics.
2. Add W1 regression tests.
3. Prepare the main Railway runtime for a durable `/data` mount without deploying until the coordinator reviews the exact diff and CI.
4. Record a Railway-volume creation/attachment action as owner-blocked if it would create billable infrastructure and cannot be done safely through the connected tooling without owner approval.
5. In parallel, harden the Trusted Action Core beginning with durable approvals and stronger binding fields.
