# P7 Multimodal World Understanding — Final Repository Qualification Evidence

Date: 2026-09-16

Branch: `p7/multimodal-world-understanding-qualification-20260915`
Draft PR: #28
P7 start base: `0d2203aa78bfe7dc935ea42887c7ba9cf1e94427`
Previous failed qualification head: `6809c325ab19eea92fc2867e5530237c98e509f0`
FINAL_P7_IMPLEMENTATION_SHA: `c0498146a0753b24da611e392181970b227a63d4`

## Scope and authority

P7 hardens the repository's existing `WorldUnderstanding`; it does not introduce a second world-model, permission system, approval authority, executor, recovery authority, memory authority or Emergency Stop authority. P7 may provide bounded governed context. P6/W7 continue to control consequential authorization, approval, execution, verification, recovery and Emergency Stop.

Persistent observations are SQLite-backed and source-attributed. The contract includes modality, stable source-event identity, device/source metadata, timestamps, confidence, privacy/payload classification, payload hash, provenance, lineage stage, parent IDs, derivation type, freshness TTL, retention policy/state, deletion/expiration, safe summary, simulation truth and device-trust state. Bounded indexed reads are used for retrieval; startup does not rebuild the observation ledger into Python memory.

## Defect closure

### 1. Sensor rejection classification

Root cause: non-finite sensor values could be rejected by the generic finite-number validator before sensor-specific validation, allowing the safe rejection classifier to choose the generic `invalid_observation_payload` category.

Repair: the existing centralized P7 rejection-classification layer is modality-aware and maps sensor/wearable numeric/value/unit validation failures to `invalid_sensor_value`. Audit/event projection remains categorical (`reason`, `modality`) and does not include the rejected value.

Regression coverage includes positive Infinity, negative Infinity, NaN, malformed string sensor values, invalid/overlong units and out-of-contract value shapes. All reject fail-closed with `invalid_sensor_value`; no observation is persisted and tested raw values do not appear in audit/event output.

### 2. `credential` / `credentials` secret-bearing fields

Root cause: the existing recursive forbidden-key set did not include normalized `credential` / `credentials` equivalents.

Repair: the existing recursive P7 secret-bearing-field protection was extended rather than duplicated. Key normalization is case-insensitive and converts hyphens/spaces to underscores. The protected set includes password/passwd/passphrase, secret/client_secret, token/access_token/refresh_token/bearer/session token, api_key/apikey, authorization, cookie/set_cookie, credential/credentials and private_key, plus protected suffix forms.

Regression coverage includes direct, nested-map, nested-list and case/spacing/hyphen variants. Rejection occurs before unsafe persistence. The tested marker is absent from the exception projection, SQLite bytes, event/Activities-style event payload, audit payload and governed action context.

### 3. Lineage / retention safety

Root cause: `expire_due()` previously tombstoned rows whose own TTL had elapsed but did not invalidate descendants whose required source lineage had become unusable. A longer-retained derived child could therefore remain active after an ephemeral RAW parent expired.

Repair: P7 now resolves descendant provenance transitively and applies fail-closed lineage invalidation for source expiration/deletion. The active usable state is separated from retained provenance/audit evidence: descendant rows are tombstoned for governed retrieval/context while lineage metadata remains available internally for audit/recovery semantics.

Qualified semantics include RAW→DERIVED; RAW→EXTRACTED→INTERPRETED→DERIVED; sibling children; multiple lineage levels; multi-parent descendants; parent/ancestor expiration; parent/ancestor deletion; restart; duplicate expiration/deletion; bounded query; owner inspection; governed action-context projection; P7→P6 context; and encrypted backup/restore. A descendant that depends on an expired/deleted required ancestor cannot remain usable as fresh governed context. An independent root remains usable when only another lineage becomes invalid.

### 4. P7→P6 test-assumption defect

The failing test incorrectly expected P6's internal `approval_id` inside a safe public operation projection. That identifier is intentionally internal and was never required for P7 context integration.

Repair: the test now validates the real authority boundary: P7 governed context can reach legitimate P6 orchestration, but it does not grant authorization; approval/execution/verification/recovery remain under existing P6/W7 control; Emergency Stop still blocks consequential work; and public projections remain free of internal approval/transaction/recovery identifiers.

P6 runtime changed: **NO**.

## Focused, adversarial and E2E qualification

P7 focused exact-head result at the final implementation SHA: **44 passed, 0 failed, 9 warnings in 7.21s**.

Adversarial coverage includes recursive nested secrets, `credential`/`credentials`, NaN, ±Infinity, malformed/out-of-contract sensor values, unsafe references, abusive timestamps, privacy-before-persistence, provenance/lineage constraints, owner API authorization, P3 trust behavior, P7→P6 authority boundaries and Emergency Stop preservation.

Deterministic E2E coverage is green for:

A. simulated observation → validation/privacy → persistence → bounded retrieval → owner inspection;
B. RAW → EXTRACTED → INTERPRETED → DERIVED;
C. duplicate → restart → duplicate → one logical observation;
D. concurrent duplicate delivery → deterministic result;
E. secret-bearing payload → reject → categorical payload-free audit;
F. fresh → stale → expired → correct context behavior;
G. source expiration/deletion → descendant unavailable as unsafe usable context;
H. P3 trusted/untrusted device behavior;
I. P7 context → P6 → existing authorization still required;
J. Emergency Stop → consequential action remains blocked despite valid P7 context.

No P6 public projection was broadened and no security assertion was weakened merely to obtain a pass.

## Performance and bounded-state evidence

Measured qualification results at 100 / 600 / 1,800 observations:

| Volume | Ingest | Restart | Bounded query | Duplicate | DB bytes | Historical rows loaded in Python |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 0.117669 s | 0.000501 s | 0.000601 s | 0.000383 s | 229,376 | 0 |
| 600 | 0.535670 s | 0.000751 s | 0.001261 s | 0.000376 s | 1,085,440 | 0 |
| 1,800 | 1.585818 s | 0.001379 s | 0.001638 s | 0.000391 s | 3,129,344 | 0 |

Additional measurements:

- provenance lookup: **0.001021 s**
- concurrent ingestion of 64 unique observations: **0.072918 s**
- descendant deletion cascade: **0.001240 s**
- expiration of 40 parent/descendant observations: **0.003209 s**
- startup historical observation materialization: **0**

These are qualification measurements, not production SLAs. They verify the key repository invariant that historical observation count does not cause the old unbounded whole-ledger Python startup materialization.

## Memory investigation

Final 45-second soak measurements:

- iterations: **6,610**
- RSS start: **46,886,912**
- RSS peak: **128,077,824**
- RSS end: **128,110,592**
- observed RSS growth: **81,223,680 bytes**
- SQLite integrity: **ok**
- P7 SQLite integrity: **ok**
- pending device requests: **0**
- P7 events: **331**
- P7 observations: **465**
- P7 DB bytes: **1,130,496**
- P7 historical observations loaded into Python memory: **0**

The process-wide RSS increase is material but is not, by itself, proof of a memory leak and is not declared harmless. Current evidence does establish that P7 is not retaining/rebuilding the historical observation ledger in Python memory. Attribution among Python allocator retention, dependency/runtime caches, test workload or another subsystem would require heap-specific diagnostics and is not inferred here.

## Encrypted backup / restore

Encrypted backup/restore plus isolated recovery qualification: **12 passed in 0.38s**.

Representative P7 state verifies observation/source-event identity, duplicate idempotency, provenance, lineage state, privacy, retention, deletion, expiration, bounded retrieval and SQLite integrity after restore. The final recovery case explicitly stores an ephemeral RAW source plus a longer-retained descendant, expires the lineage, backs it up, restores it and verifies neither source nor descendant becomes active again.

## Full repository and security gate

Exact frozen implementation direct CI:

- `pip check` — PASS (`No broken requirements found.`)
- compileall — PASS
- full repository `pytest -q` — **1085 passed, 0 failed, 15 warnings in 38.77s**

Reliability and Security independently proved:

- `pip-audit -r requirements.txt` — PASS (`No known vulnerabilities found`)
- compileall — PASS
- P7 focused qualification — **44 passed, 9 warnings in 7.21s**
- full repository — **1085 passed, 0 failed, 15 warnings in 40.46s**
- encrypted backup/restore/recovery — **12 passed in 0.38s**
- final 45-second soak — PASS with both SQLite integrity checks `ok` and pending device requests 0

## Frozen implementation workflow gate

| Workflow | Run | Run ID | Head SHA | Conclusion |
| --- | ---: | ---: | --- | --- |
| CI | #1140 | `35042584877` | `c0498146a0753b24da611e392181970b227a63d4` | PASS |
| Reliability and Security | #273 | `35042584893` | `c0498146a0753b24da611e392181970b227a63d4` | PASS |
| P3 iPhone PWA | #225 | `35042584920` | `c0498146a0753b24da611e392181970b227a63d4` | PASS |
| Android Instrumentation | #272 | `35042584924` | `c0498146a0753b24da611e392181970b227a63d4` | PASS |
| Package Validation | #272 | `35042584939` | `c0498146a0753b24da611e392181970b227a63d4` | PASS |
| iOS Companion | #254 | `35042584896` | `c0498146a0753b24da611e392181970b227a63d4` | PASS |

Implementation gate: **6/6 PASS**.

GitHub pull-request workflows validate the generated PR merge ref against the unchanged base while reporting the frozen branch head SHA. A direct push CI run separately checked out `c0498146a0753b24da611e392181970b227a63d4` itself, providing an exact-SHA full-repository check.

## Cumulative diff review

Base: `0d2203aa78bfe7dc935ea42887c7ba9cf1e94427`
Final implementation: `c0498146a0753b24da611e392181970b227a63d4`

Cumulative diff: **18 commits, 9 files, +2,387 / -30**.

Files are limited to P7 implementation/API/program wiring, the reliability workflow, soak instrumentation and P7 tests. No P6 runtime file changed. No P8/P9/P10 implementation, Railway/production deployment, OAuth activation, production credentials, signing, physical-device qualification or new action authority was introduced.

## Evidence boundary

At this documentation commit the final evidence-head workflow rerun is still required. Only after that exact evidence SHA is green may P7 be classified repository-automated evidence complete.

The immutable evidence document records implementation-head workflow facts. Evidence-head workflow results necessarily execute after the evidence commit and are recorded in the final closure report rather than prospectively embedded here.

REAL_CAMERA_VERIFIED = NO
REAL_MICROPHONE_VERIFIED = NO
REAL_LOCATION_VERIFIED = NO
REAL_WEARABLE_VERIFIED = NO
PHYSICAL_MULTIMODAL_VERIFIED = NO
LIVE_SERVICE_VERIFIED = NO
PRODUCTION_VERIFIED = NO

P8_STARTED = NO
