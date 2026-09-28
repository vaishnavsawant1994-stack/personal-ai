# Personal AI — Capability Matrix

Baseline date: 2026-09-16

Statuses distinguish automated repository evidence from live service, real local/external model, physical-device, signed-distribution and production evidence. Automated mocks, simulators and deterministic provider adapters are never classified as physical/live provider proof.

| Capability | Status | Automated evidence | Remaining boundary | Exact SHA / next |
| --- | --- | --- | --- | --- |
| Home / AI Core | QUALIFICATION | UI/PWA workflows green | physical UX incomplete | frozen design |
| Trusted Action Core | PARTIAL | durable binding/replay/epoch/reauth; reused by W7.1-W7.6 | live operational proof partial | preserve authority |
| W7.1 Durable Operator Transaction Core | AUTOMATED VALIDATED | durable transaction/action/audit, cancellation, recovery, Emergency Stop | physical qualification pending | frozen |
| W7.2 Observation / Sensitive Evidence | AUTOMATED VALIDATED | 85 focused; 557 full | physical desktop/browser proof pending | frozen evidence |
| W7.3 Allowlists / Data-Safety Policies | AUTOMATED VALIDATED | implementation + docs gates complete | physical policy qualification pending | frozen evidence |
| W7.4 Safe Browser Operator | AUTOMATED VALIDATED | implementation + docs gates complete | real-site/physical-browser proof pending | frozen evidence |
| W7.5 Safe Desktop / File Operator | AUTOMATED VALIDATED | implementation + docs gates complete | real-world Windows/physical/production qualification pending | frozen evidence |
| W7.6 Verification and Recovery | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED | frozen W7 baseline contains recovery implementation/evidence | physical/production qualification separate | preserve frozen W7 |
| W8 Model Health / Failover / Observability | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED / REPOSITORY-AUTOMATED SCOPE COMPLETE | implementation and documentation exact-head workflows 6/6 PASS | live-provider/local-model/physical/production qualification separate | implementation `42616b2e8faca9b16a5695ac319ea78200e7af74`; evidence `bd8bdcfb25aee06ea078408e0a0da477fcfdfbce` |
| P4 Everyday Personal Intelligence | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED FOR RETRIEVAL-REMINDER TRANCHE | durable lifecycle and deterministic retrieval/reminder qualification | live delivery/daily-use/physical proof separate | `14f0d5dbe532d5edf7ec910270d0d9114f5f9d8b` |
| P5 Second Brain / Life Graph | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED FOR RETRIEVAL-REMINDER TRANCHE | bounded retrieval, temporal/current truth, deletion/retention/context budget | larger real corpus/media/physical proof separate | `14f0d5dbe532d5edf7ec910270d0d9114f5f9d8b` |
| P6 Autonomous Operations | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED | governed delegation composes through existing AgentExecutor/AutomationEngine/W7 | autonomous/live/physical/production qualification separate | implementation `e674ee80b66ba6c6dbe734ef1825df6a56c19d3f`; PR #27 |
| P7 Multimodal Understanding | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED / REPOSITORY-AUTOMATED SCOPE COMPLETE | implementation and evidence exact-head gates 6/6; hardened canonical WorldUnderstanding | real camera/mic/location/wearable/live/production separate | implementation `c0498146a0753b24da611e392181970b227a63d4`; evidence `5f13ff2a994e2d257ba1c8d4d4f6cdd6a32d481e`; PR #28 |
| P8 Personal AI Everywhere | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED / REPOSITORY-AUTOMATED SCOPE COMPLETE | governed cross-device continuity; implementation and evidence exact-head gates 6/6 | real iPhone/Android/desktop cross-device and live/production separate | implementation `041584c50e2e2df8e74aa67843eebd2c2e0e058c`; evidence `bd36011cc71d57110e60843019e52bc6b1963a61`; PR #30 |
| P9 Hybrid AI | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED / REPOSITORY-AUTOMATED SCOPE COMPLETE | canonical W8 router + deterministic privacy/capability/owner policy; implementation and evidence exact-head gates 6/6 | real local/external provider/live/production remain separate | implementation `bfb9b574e2dfbd2e0026ab1affbe74ba9a17e7eb`; evidence `0e1081751a7efafc9c9f35a2afb9c6d431875b92`; PR #31 |
| P10 Advanced Autonomous Intelligence | IMPLEMENTED / INTEGRATED / IMPLEMENTATION-HEAD AUTOMATED VALIDATED | 54 P10 focused/adversarial/A-X/durability tests; 1238 full; encrypted recovery 15; implementation workflows 6/6; P6/W7/P7/P8/P9/W8 authorities reused | documentation/evidence exact-head gate; physical/live/provider/production proof separate | frozen implementation `4544df7a68d447871e17c3c2dc221efc12722abb`; PR #32 |
| Computer operator overall | AUTOMATED SCOPE CANDIDATE COMPLETE | W7.1-W7.6 automated authorities integrated | physical/production qualification remain | preserve frozen W7 |
| Google connector software scope | AUTOMATED VALIDATED / LIVE PENDING | W6 software gates green | real Google account qualification owner-deferred | preserve blocker |
| Production durable storage | BLOCKED | fail-closed hosted guard exists | approved production volume absent | future production gate |
| Physical P3 | BLOCKED / DEFERRED | automated P3 green | mandatory real-device evidence incomplete | final pre-release physical protocol |
| W10 Signed Distribution | BLOCKED / QUALIFICATION | unsigned/dev package and simulator/instrumentation evidence exists | physical-device/signing credentials missing | readiness only until owner gates |
| W12 Release Readiness | PARTIAL | strong repository/automated evidence | live OAuth/providers/storage, physical devices, signing and production gates | no production promotion |

## P10 Advanced Autonomy implementation qualification

P10 starts exactly from P9 evidence `0e1081751a7efafc9c9f35a2afb9c6d431875b92` on `p10/advanced-autonomy-qualification-20260916`, draft PR #32. Frozen implementation: `4544df7a68d447871e17c3c2dc221efc12722abb`.

`AdvancedAutonomy` is orchestration-only. It owns bounded goals, structured plans, dependency scheduling, replanning, owner pause/resume/cancel, suggestions, worker-agent metadata and durable orchestration state. It does not become identity, permission, approval, execution, verification, recovery, Emergency Stop, Memory, Knowledge, world-context, continuity, model-routing or model-health authority.

P10 composes through P6/W7 for consequential operations, approvals, verification and recovery; P7 for bounded observation context; P8 for trusted continuity; P9 for advisory governed model computation; and W8 through P9 for health/failover/observability. Model, agent and tool output remain untrusted and cannot grant authority. LOCAL_ONLY does not gain external fallback.

Implementation qualification: **54 P10 focused/adversarial/A-X/durability tests PASS**; full repository **1238 passed, 0 failed, 24 warnings**; encrypted recovery **15 passed**; compileall and `pip check` PASS; `pip-audit` reports no known vulnerabilities. Concurrency qualification covers shared SQLite persistence, owner/plan isolation, concurrent event writes and SQLite integrity. Nested telemetry sanitization removes sensitive keys recursively and history is bounded.

Final 45-second P10 soak: **6,330 iterations**, bounded event history **500**, SQLite integrity `ok`; deterministic goal/plan transitions, cancellation, replanning, E-stop, restart and proactivity exercised. These are repository qualification measurements, not production/live autonomy evidence.

Implementation exact-head workflows at `4544df7a68d447871e17c3c2dc221efc12722abb`:

- CI #1221 / `35086639540` — PASS
- Reliability and Security #303 / `35086639510` — PASS
- P3 iPhone PWA #241 / `35086639531` — PASS
- Android Instrumentation #302 / `35086639552` — PASS
- Package Validation #302 / `35086639563` — PASS
- iOS Companion #284 / `35086639521` — PASS

Implementation gate: **6/6 PASS**. Evidence remains documentation-only until the second exact-head gate completes.

## Frozen authority boundaries

W7 remains consequential-action/transaction/approval/verification/recovery/Emergency Stop authority. W8 remains model health/failover/observability authority. Second Brain remains Memory authority. Knowledge remains distinct from Memory. P7 remains world-understanding context authority. P8 remains trusted continuity/device/session authority. P9 decides which eligible intelligence resource may compute a result and never grants permission. P10 plans and orchestrates but does not gain unrestricted authority. The owner remains authoritative.

REAL_LOCAL_MODEL_VERIFIED = NO
REAL_EXTERNAL_PROVIDER_VERIFIED = NO
PHYSICAL_IPHONE_VERIFIED = NO
PHYSICAL_ANDROID_VERIFIED = NO
PHYSICAL_DESKTOP_VERIFIED = NO
REAL_MICROPHONE_VERIFIED = NO
REAL_CAMERA_VERIFIED = NO
REAL_LOCATION_VERIFIED = NO
REAL_WEARABLE_VERIFIED = NO
LIVE_BACKGROUND_AUTONOMY_VERIFIED = NO
LIVE_HYBRID_ROUTING_VERIFIED = NO
LIVE_SERVICE_VERIFIED = NO
PRODUCTION_VERIFIED = NO
