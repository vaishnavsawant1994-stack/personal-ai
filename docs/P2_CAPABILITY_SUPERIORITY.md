# Personal AI — P2 Capability Superiority

Status: FROZEN DEVELOPMENT DIRECTION
Baseline: Home V1 remains frozen. No Home redesign is allowed unless a verified usability defect requires it.

## Program objective

Turn Personal AI from a polished assistant shell into a continuously useful personal intelligence while preserving the approved Home V1 experience, permission model, audit trail and clean-room codebase.

## Milestones

| Stage | Milestone | Objective |
| --- | --- | --- |
| P2.1 | Voice Intelligence | Natural continuous conversation with barge-in and state synchronization |
| P2.2 | Screen + Computer Intelligence | Observe → Understand → Act → Verify |
| P2.3 | Proactive Intelligence | Calm relevance-driven suggestions and notifications |
| P2.4 | Autonomous Automation | Reliable event/schedule workflows with retries, approvals and history |
| P2.5 | Second Brain V2 | Salience, decay, conflict handling, temporal/episodic/semantic memory |
| P2.6 | Cross-Device Continuity | One persistent context across desktop, phone, browser and future devices |
| P2.7 | Capability Benchmark | Measurable capability levels and repeatable competitive tasks |

## Governing rules

1. Home V1 is the shell; capabilities plug into it through existing semantic states.
2. Models may propose actions but tools and permission policy decide whether actions execute.
3. Desktop control must never be blind: observe before action and verify after action.
4. Consequential/external/destructive actions remain approval-scoped according to the existing risk engine.
5. Proactivity must use relevance, cooldowns and interruption budgets; silence is a valid outcome.
6. Memory keeps provenance, confidence, sensitivity and temporal status; new claims do not silently erase history.
7. Cross-device access uses one memory/context authority rather than creating separate assistants per device.
8. Benchmarks measure actual behavior using Not supported → Prototype → Functional → Reliable → Production → Superior.
9. Brahma Echo is an external benchmark only. No Brahma source code is copied or reproduced.
10. Every P2 capability must expose evidence through tests, events, activity history or audit records.

## State integration

- Voice → listening / understanding / thinking / speaking
- Screen perception → understanding
- Memory retrieval → memory
- External knowledge retrieval → knowledge
- Automation and computer control → acting
- Consequential approval → approval
- Failures → error

## Completion gate

P2 is complete only when P2.1–P2.7 are integrated, tests pass, CI is green on the exact candidate, and post-merge CI is green on main. Hardware/provider-dependent behavior may remain explicitly marked as requiring real-device/provider validation; such limits must not be represented as laboratory-validated production behavior.
