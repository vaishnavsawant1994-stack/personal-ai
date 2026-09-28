# Personal AI — Post-W8 Qualification, Activation and Dependency-Order Checkpoint

Date: 2026-09-15

## Frozen evidence

- W7 frozen baseline: `dad974fc1058678a07daae1702849178d2cf2dd2`.
- W8 final implementation: `42616b2e8faca9b16a5695ac319ea78200e7af74`.
- W8 final documentation/evidence head: `bd8bdcfb25aee06ea078408e0a0da477fcfdfbce`.
- W8 historical failed candidate retained only as remediation evidence: `1a9d379f8cdb372e583eb01dfd6373d307c18db8`.
- W8 is IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED / REPOSITORY-AUTOMATED SCOPE COMPLETE. It is not live-provider, real-local-model, physical-device, signed-distribution or production verification.
- PR #24 remains open, draft and unmerged. No production/Railway/OAuth/provider/signing mutation was performed by this post-W8 tranche.

## Classification legend

- A — CODE / INTEGRATION WORK: executable in repository now.
- B — AUTOMATED QUALIFICATION: executable through deterministic CI/simulation/harnesses.
- C — OWNER / ACCOUNT REQUIRED: owner login, consent, credential or explicit external approval.
- D — PHYSICAL DEVICE REQUIRED: physical iPhone/iPad/Windows/Android/sensor hardware.
- E — PAID INFRASTRUCTURE REQUIRED: approved paid hosted service/infrastructure.
- F — PRODUCTION GATE: explicit promotion/deployment approval.
- G — SIGNING / RELEASE CREDENTIAL REQUIRED: Apple/Android/Windows signing/notarization identity.

## Authoritative post-W8 remaining-work register

| Order | Workstream | Capability | Current maturity | Missing evidence / work | Dependency / blocker | Class | Executable now | Owner action now |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | P4 | Daily briefing + Second Brain context | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED | daily-use/live acceptance remains | physical/live usage later | A/B completed this tranche; D later | YES | NO |
| 2 | P5 | Second Brain ↔ Life Graph linking | IMPLEMENTED / INTEGRATED / AUTOMATED VALIDATED | long-term corpus/retrieval quality and physical P3.5 remain | physical P3.5 later | A/B completed this tranche; B/D remaining | YES | NO |
| 3 | P5 | Graph retrieval quality / long-term corpus qualification | IMPLEMENTED FOUNDATION / PARTIAL QUALIFICATION | representative large corpus, relevance/temporal/conflict quality metrics | none for deterministic corpus | B | YES | NO |
| 4 | P5 | Media extraction quality | PARTIAL | image/document/media extraction accuracy evidence | source fixtures available; real devices optional later | A/B | YES | NO |
| 5 | P4 | Reminder/follow-up execution and proactive precision | FOUNDATION / PARTIAL | deterministic delivery lifecycle and precision/recall evidence; real notification acceptance | live service/device delivery later | A/B; D later | YES | NO |
| 6 | P6 | PersonalOperations → governed AgentExecutor/AutomationEngine delegation | FOUNDATION / PARTIAL | the P6 facade currently marks non-consequential plans ready but does not itself delegate; integration qualification remains | must preserve W7 authority and P3 activation gates | A/B | YES | NO |
| 7 | P6 | Real long-running automation qualification | AUTOMATED FOUNDATION | ≥20 recovery trials, ≥8 cumulative production-like hours, no duplicate external side effects | P3 activation + representative external environment | B/D/F as evidence class grows | PARTLY | LATER |
| 8 | P7 | Normalized multimodal observation ledger | IMPLEMENTED / AUTOMATED FOUNDATION | broader modality/permission/restart deterministic tests; real sensor evidence | real camera/location/wearable availability | B; D for sensors | YES | NO |
| 9 | P8 | Cross-surface continuity | IMPLEMENTED FOUNDATION / PARTIAL | actual surface-by-surface runtime and real handoff evidence | P3.6 physical continuity | A/B/D | PARTLY | LATER |
| 10 | P9/W8 | Model health/failover/observability | AUTOMATED VALIDATED | live provider qualification and real local-model qualification | credentials/cost/local runtime | C/E and D/E | NO for live proof | YES LATER |
| 11 | P10 | Persistent agents/policy/budgets/Emergency Stop/outcomes | IMPLEMENTED / AUTOMATED FOUNDATION | deeper governed-execution integration evidence; activation proof | P3 permissions/automation/memory/continuity/reliability | B now; D/F later | YES for validation | NO |
| 12 | P3.1 | Real voice: listen/speak/interruption | INSTRUMENTED / AUTOMATED TESTED | physical mic/speaker turns, barge-in rates and latency | physical iPhone/device | D | NO | YES LATER |
| 13 | P3.2 | Screen perception / governed computer | AUTOMATED FOUNDATION | ≥25 real Observe→Understand→Permission→Act→Verify trials | physical desktop/browser | D | NO | YES LATER |
| 14 | P3.3 | Permission/identity/safety | AUTOMATED VALIDATED FOUNDATION | ≥50 physical boundary trials, 100% safety pass | physical trusted device | D | NO | YES LATER |
| 15 | P3.4 | Workflow recovery | AUTOMATED VALIDATED FOUNDATION | production-like duration and real external-side-effect recovery evidence | representative environment | D/F, sometimes C/E | PARTLY | LATER |
| 16 | P3.5 | Second Brain quality | AUTOMATED FOUNDATION | ≥50 real recall/context trials, retrieval latency, temporal/conflict/source traceability | physical owner sessions | D | NO for real-device gate | YES LATER |
| 17 | P3.6 | Cross-device continuity | AUTOMATED FOUNDATION | ≥20 real handoff/resume trials and revocation proof | at least two real surfaces/devices as applicable | D | NO | YES LATER |
| 18 | P3.7 | Reliability/soak | AUTOMATED SOAK GREEN | ≥200 production-like operations and ≥4 cumulative hours | representative runtime | B/F | PARTLY | LATER |
| 19 | W6/P4 | Live email/calendar/Drive/Sheets connectors | SOFTWARE AUTOMATED VALIDATED / LIVE PENDING | owner OAuth consent and live account evidence | owner consent; isolated paid qualification infra currently deferred | C/E | NO for live proof | YES LATER |
| 20 | W1/W12 | Main production durable storage | REPOSITORY PREPARED / PRODUCTION BLOCKED | persistent production volume and redeploy/restore evidence | Railway/paid/production approval | C/E/F | NO for production mutation | YES LATER |
| 21 | W10 | Windows signed distribution | PACKAGE AUTOMATED / SIGNED & PHYSICAL PENDING | signing certificate, SmartScreen/reputation, install/update/uninstall/rollback on real Windows | signing identity + physical Windows | D/G | readiness YES; signing NO | YES LATER |
| 22 | W10 | Android signed distribution | AUTOMATED COMPANION/INSTRUMENTATION / RELEASE PENDING | release keystore, upgrade/distribution and physical device qualification | signing identity + Android device | D/G | readiness YES; signing NO | YES LATER |
| 23 | W10 | iOS native distribution | SIMULATOR AUTOMATED / RELEASE PENDING | Apple Developer/App Store Connect provisioning/signing/TestFlight and physical iPhone | Apple account/signing + physical device | C/D/G | unsigned prep YES; signing NO | YES LATER |
| 24 | W12 | Release readiness | PARTIAL | live OAuth, production storage/service, physical qualification, signing | external gates above | C/D/E/F/G | repository checks YES | YES LATER |

Priority is dependency- and user-value-based, not milestone-number based. W10 therefore remains behind higher-value unblocked P4/P5/P6 qualification/integration work.

## P3 reassessment

- Permissions/identity/trust enforcement: implemented and extensively automated; physical P3.3 qualification remains absent.
- Trusted-device enrollment: implemented for the iPhone PWA and automated; physical owner enrollment evidence remains absent.
- iPhone PWA: implemented and automated; a workflow PASS is not physical iPhone verification.
- Continuity/session handling: durable implementation and automated tests exist; physical cross-device P3.6 remains absent.
- Speech input/spoken reply/interruption: software path and qualification instrumentation exist; physical microphone/speaker/barge-in evidence remains absent.
- Automation authority: W7 is the authoritative consequential-action safety foundation; P6/P10 remain fail-closed until prerequisite P3 evidence is present.
- Browser behavior: W7 browser operator automated evidence exists; real-site/physical-browser qualification remains pending.
- Physical-device evidence: not promoted by simulator/CI evidence.

## P4 reassessment

Goals, reminders, follow-ups, commitments, attention queue, evidence-based forgotten-item reporting, daily briefing, connected-service awareness and continuity-backed context switching exist as software foundations. This tranche found and repaired a real integration defect: `EverydayIntelligence.briefing()` called a nonexistent `SecondBrain.search()` method and swallowed the exception, causing `relevant_memory` to remain empty. It now uses the authoritative `SecondBrain.context()` path and has behavioral regression coverage.

Live email/calendar evidence, real reminder/device delivery, daily-use acceptance and proactive precision/recall remain separate qualification items.

## P5 reassessment

Second Brain already provided authoritative memory, vector-assisted/lexical retrieval, salience, temporal search, relationships, supersession/conflict handling, evidence references, deletion and retention. Life Graph already provided typed life entities, causal/context relationships, timeline and evidence-backed decision explanation, but it was a separate database with no linking layer to Second Brain.

This tranche adds a read-through `SecondBrainLifeGraph` bridge rather than duplicating memory into another persistence authority. The bridge projects live memory nodes, relationships and authoritative supersession into the P5 graph view; deletion/retention take effect immediately because there is no copied memory state. Unsupported memory types remain visible as generic `memory` nodes. Sensitive/secret memories fail closed unless the existing trusted-device scope allows them. Owner inspection APIs expose graph/timeline views under the existing authentication model.

Remaining P5 work is deterministic graph-retrieval/long-term-corpus/media-extraction quality qualification plus real-device P3.5.

## P6-P10 reassessment

- P6: persisted planning and P3 fail-closed gates exist; consequential plans require approval. The P6 facade still reports non-consequential plans as ready/delegated false, so direct composition with the existing governed executor/automation engine remains an unblocked integration/qualification opportunity. W7 authority must remain unchanged.
- P7: normalized source-attributed persistent observations exist for screen/camera/image/document/audio/location/device sensors/wearables. This is software support only; it does not prove sensor availability.
- P8: a shared surface registry/continuity foundation exists. iPhone PWA, iOS companion foundation, desktop/web and Android-supported surfaces have real code; watch/earbuds/car/home/AR entries are architectural foundations, not completed physical surfaces.
- P9: W8 supplies the authoritative runtime resilience/health/failover/observability work. Automated scope is validated; live provider and real local model remain unverified.
- P10: persisted agents, tool allowlists, budgets, Emergency Stop, long-horizon plan stages, outcome evidence, self-evaluation and scenario analysis exist. Agents remain disabled/fail-closed without prerequisite evidence.

## Implementation tranche executed

Branch: `p5/second-brain-life-graph-qualification-20260915`.
Draft PR: #25.
Base: frozen W8 documentation head `bd8bdcfb25aee06ea078408e0a0da477fcfdfbce`.
Implementation SHA: `fc8f1aeb5a8121f0faf911b6840b7ec15d48b609`.

Changed implementation/test files:

- `future_intelligence/everyday.py`
- `future_intelligence/program.py`
- `future_intelligence/second_brain_graph.py`
- `server/memory_knowledge_inspection.py`
- `tests/test_memory_knowledge_inspection_api.py`
- `tests/test_p4_p10_future_intelligence.py`
- `tests/test_p5_second_brain_life_graph.py`

Exact implementation-head validation:

| Workflow | Run | Run ID | Result |
| --- | ---: | ---: | --- |
| CI | #1060 | `34980195417` | PASS |
| Reliability and Security | #245 | `34980195624` | PASS |
| Android Instrumentation | #244 | `34980195358` | PASS |
| Package Validation | #244 | `34980195728` | PASS |
| iOS Companion | #226 | `34980195661` | PASS |
| P3 iPhone PWA | path-filtered N/A | — | N/A — no P3/PWA path changed |

Full repository pytest: **972 passed, 0 failed, 8 warnings in 26.17s**. `pip check` PASS. Compileall PASS. Reliability/Security passed `pip-audit`, full pytest, isolated encrypted backup/restore and 45-second soak. Package Validation passed macOS, Windows and Ubuntu. iOS evidence is simulator evidence only.

## W10 readiness boundary

Automated packaging/build infrastructure may continue without signing credentials, but W10 must not be called signed or physical-ready. Windows needs an owner-controlled code-signing identity and real install/update/uninstall/recovery trials. Android needs an owner-controlled release keystore and real-device upgrade/distribution trials. Native iOS needs Apple Developer/App Store Connect provisioning/signing and physical iPhone/TestFlight evidence. PWA qualification remains distinct from native iOS distribution.

## W12 readiness categories

- REPOSITORY READY: strong for validated automated scopes; remaining unblocked P4/P5/P6 work still exists.
- AUTOMATED READY: strong but capability-specific; do not collapse it into live or physical readiness.
- LIVE SERVICE READY: NO overall; OAuth/provider/storage gates remain.
- PHYSICAL DEVICE READY: NO overall; mandatory P3/Windows/iPhone/Android evidence remains.
- SIGNED DISTRIBUTION READY: NO.
- PRODUCTION READY: NO.

## Live-provider qualification protocol

When explicitly owner-approved and credentials are installed outside evidence/logs, use the minimum calls needed to verify authentication, model availability, one successful generation, streaming/structured output/tool capability where supported, timeout classification, rate-limit classification, bounded failover, safe telemetry/redaction, owner disable and recovery. Never capture provider credentials or raw secrets in qualification evidence. Paid calls require explicit owner approval.

## Real local-model qualification protocol

On an actual local runtime/model: prove process startup, model presence/load, health detection, generation, latency/context behavior, failure/recovery, offline operation, privacy routing, prohibition of external fallback for local-only tasks, resource-pressure handling and restart recovery. Automated fake/local-unavailable tests do not satisfy this gate.

## Physical qualification protocols

Physical iPhone evidence must cover trusted enrollment/session, PWA/native surface, microphone, speech, spoken response, intentional interruption, continuity, background/foreground, reconnect and permission behavior. Physical Windows evidence must cover install/startup, desktop presence, microphone/speaker, browser/file operators, approval, Emergency Stop, recovery/restart and update/uninstall. Android must be qualified only to the implemented scope. Each trial records ACTION, EXPECTED RESULT, EVIDENCE and PASS/FAIL; simulator evidence is never relabeled physical.

## PR strategy

PR #22 remains frozen. PR #24 remains open/draft/unmerged as the frozen W8 review boundary. Post-W8 PR #25 is deliberately stacked on the exact W8 documentation head so its diff contains only the post-W8 tranche. Do not merge #24 or retarget/promote #25 merely because CI is green; first preserve exact-head evidence and then use the project’s integration-baseline promotion decision explicitly.
