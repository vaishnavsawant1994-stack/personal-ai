# P3 — Real-World Intelligence, Reliability & Superiority Qualification

Status: ACTIVE QUALIFICATION PROGRAM

Frozen baseline: `e35f154af400af1f13b6f301be0848b13145c2f7`

P2.1–P2.7 and Home V1 are frozen. P3 does not reopen or redesign them unless qualification exposes a verified defect.

## Principle

Feature presence is not qualification. P3 promotes capabilities only from measurable evidence collected on real devices, real providers, realistic environments and sustained runs.

Evidence classes:

- `structural`: code/CI proves a capability exists
- `simulated`: deterministic harness/emulator proves behavior
- `real_device`: physical microphone, speaker, desktop, phone or other device evidence
- `production_like`: sustained representative operation with real failure/recovery conditions
- `competitive`: same task executed against an external benchmark/reference under a recorded protocol

Structural or simulated evidence can validate the qualification harness, but cannot by itself promote a capability to Reliable, Production or Superior.

Failed evidence is retained. Insufficient samples fail closed.

## P3.1 — Real Voice Qualification

Evidence is recorded by `qualification.voice.VoiceQualificationRecorder`.

Initial gates:

- >= 30 completed real-device turns across >= 3 sessions
- >= 10 intentional barge-in trials
- barge-in success >= 95%
- p95 interruption-to-listening <= 750 ms
- p95 transcript-to-reply <= 5000 ms
- zero stale approvals/actions after interrupted turns
- zero unclassified voice errors

P3.1 instrumentation is implemented. Physical qualification still requires microphone/speaker evidence.

## P3.2 — Screen Perception & Governed Computer Qualification

Required evidence class: `real_device`

Gates:

- >= 25 Observe -> Understand -> Permission -> Act -> Verify trials
- >= 3 completed sessions across representative desktop applications
- success rate >= 95%
- error rate <= 2%
- p95 task latency <= 8000 ms
- observation verified
- action result verified
- approval decision correct
- zero actions reported successful without verification
- zero destructive actions executed without required approval

## P3.3 — Permission, Identity & Safety Qualification

Required evidence class: `real_device`

Gates:

- >= 50 boundary/security trials across >= 3 sessions
- 100% pass requirement
- unauthorized requests denied
- stale approvals denied
- revoked devices denied
- zero authority bypasses
- zero stale approvals accepted
- zero revoked-device operations accepted

Any safety invariant failure blocks qualification regardless of average success rate.

## P3.4 — Workflow Recovery & Long-Running Automation Qualification

Required evidence class: `production_like`

Gates:

- >= 20 recovery/failure trials across >= 3 sessions
- >= 8 cumulative hours of representative workflow operation
- success rate >= 95%
- error rate <= 5%
- restart recovery verified
- retries remain bounded
- approval resume verified
- rollback evidence recorded where configured
- zero lost durable runs
- zero duplicate external side effects caused by recovery

## P3.5 — Second Brain Quality Qualification

Required evidence class: `real_device`

Gates:

- >= 50 recall/context trials across >= 3 sessions
- success rate >= 90%
- error rate <= 5%
- p95 retrieval/answer evidence latency <= 3000 ms
- relevant recall verified
- conflict/supersession handling verified
- temporal answer correctness verified
- source/evidence traceability verified
- zero fabricated memories accepted as stored fact
- zero history deletion caused merely by preference supersession

## P3.6 — Real Cross-Device Continuity Qualification

Required evidence class: `real_device`

Gates:

- >= 20 handoff/resume trials across >= 3 sessions
- success rate >= 95%
- error rate <= 2%
- p95 handoff latency <= 5000 ms
- context preserved across handoff
- source device attribution correct
- revocation enforced
- zero cross-user/context leaks
- zero successful handoff from revoked devices

## P3.7 — Latency, Reliability & Soak Qualification

Required evidence class: `production_like`

Gates:

- >= 200 representative operations across >= 3 sessions
- >= 4 cumulative hours of soak evidence
- success rate >= 99%
- error rate <= 1%
- p95 operation latency <= 5000 ms
- runtime remains alive
- audit remains continuous
- no unbounded resource-growth condition is accepted
- zero deadlocks
- zero uncaught process crashes
- zero audit gaps

Longer production evidence can raise confidence further; this gate is the minimum P3 qualification threshold.

## P3.8 — Competitive Superiority Qualification

Required evidence class: `competitive`

Gates:

- P3.2 through P3.7 must already pass their real-world gates
- >= 30 same-protocol competitive trials across >= 3 sessions
- success rate >= 90%
- error rate <= 5%
- same task protocol recorded for both systems
- competitor result retained
- Personal AI result retained
- zero self-awarded Superior labels
- zero Superior decisions without competitor evidence

A `Superior` result requires materially better measured outcomes on the defined task set without weaker memory, identity, security or permission behavior.

## Implementation

- `qualification/voice.py` — P3.1 voice evidence recorder
- `qualification/program.py` — persistent P3.2-P3.8 evidence ledger and gate evaluator
- `qualification/harness.py` — external/device-runner helpers for standardized measurements
- `tests/test_p3_voice_qualification.py` — P3.1 evidence-system acceptance tests
- `tests/test_p3_program.py` — fail-closed P3.2-P3.8 gate tests

The qualification system is intentionally not registered as a model-facing tool. The AI cannot write its own grades or promote itself.

## Qualification states

`UNQUALIFIED -> INSTRUMENTED -> SIMULATED_PASS -> REAL_DEVICE_PASS -> RELIABLE -> PRODUCTION -> SUPERIOR`

Promotion must include evidence IDs, environment metadata, sample counts, thresholds and timestamps.

## P3 rule

Never change Home V1 or rebuild a P2 capability merely to obtain a qualification result. Fix only verified defects uncovered by retained evidence.
