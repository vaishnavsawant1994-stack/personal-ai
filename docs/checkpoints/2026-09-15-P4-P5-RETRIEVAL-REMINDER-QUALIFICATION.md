# P4/P5 Retrieval Intelligence + Reminder/Follow-up Lifecycle Qualification

Date: 2026-09-15

## Frozen starting point

- W7 frozen baseline: `dad974fc1058678a07daae1702849178d2cf2dd2`
- W8 implementation: `42616b2e8faca9b16a5695ac319ea78200e7af74`
- W8 evidence: `bd8bdcfb25aee06ea078408e0a0da477fcfdfbce`
- Prior Post-W8 P4/P5 implementation: `fc8f1aeb5a8121f0faf911b6840b7ec15d48b609`
- Starting evidence head: `4985dd014ec8c29c9f90c2dba8f153ea8a5bb969`
- Prior PR #25 remains OPEN / DRAFT / UNMERGED.

## Branch / PR

- Branch: `p4-p5/retrieval-reminder-qualification-20260915`
- Draft PR: #26
- PR base branch: `p5/second-brain-life-graph-qualification-20260915`
- PR base SHA at creation: `4985dd014ec8c29c9f90c2dba8f153ea8a5bb969`
- Final implementation SHA: `14f0d5dbe532d5edf7ec910270d0d9114f5f9d8b`

PR #24 and PR #25 were not mutated. No merge was performed.

## Retrieval architecture audited

The existing Second Brain already provided:

- authoritative durable memory through `MemoryStore`;
- lexical subject/content search;
- optional semantic/vector retrieval through existing `VectorStore`;
- importance, confidence, verification, usage and recency salience;
- temporal fields (`occurred_at`, `valid_from`, `valid_to`);
- explicit supersession/conflict records;
- source/evidence references;
- exact-content duplicate suppression;
- deletion, retention and graph relationships;
- retrieval explanations.

The audit found four concrete gaps relevant to daily use:

1. relationship count was explanatory only; `relationship_contribution` was hard-coded `0.0` and graph context did not influence retrieval;
2. direct `SecondBrain.context()` did not fail closed to normal sensitivity when a caller omitted an explicit filter;
3. current-truth retrieval was implicit ranking rather than an explicit contract, so retained historical/superseded memories could appear in ordinary context;
4. no bounded context-character budget or time-valid (`what was true then?`) helper existed.

The existing vector store remains a SQLite/full-scan foundation. This tranche did not create a parallel retrieval engine or ANN index prematurely.

## Retrieval implementation

The existing `SecondBrain` was extended in place.

Actual ranking factors are now explicit and sum to one before historical down-ranking:

- semantic 0.30;
- importance 0.23;
- confidence 0.17;
- verified 0.07;
- usage 0.06;
- recency 0.10;
- visible relationship contribution 0.07.

Retained historical memory still receives the existing 0.28 multiplier. Retrieval explanations expose actual contribution values used by ranking rather than invented factors.

New/strengthened contracts:

- default allowed sensitivity = `normal` (fail closed);
- permission filtering precedes graph expansion and graph-count metadata;
- bounded one-hop related-memory expansion can contribute real relationship relevance;
- `current_truth()` excludes rows with `valid_to`;
- `context_at()` resolves memories that were valid at a requested time;
- `truth_state` distinguishes `CURRENT`, `HISTORICAL`, `SUPERSEDED` while preserving legacy `memory_state=active/historical` compatibility;
- context-character budgeting limits returned context without mutating memory;
- deletion and retention continue to use the authoritative memory store/vector deletion path.

Life Graph remains read-through and does not become a persistence authority.

## Corpus / temporal / conflict qualification

Deterministic datasets qualified progressively:

| Memories | Expected | Result | Qualification latency |
| ---: | --- | --- | ---: |
| 100 | unique target first | PASS | ~3.943 ms |
| 1,000 | unique target first | PASS | ~18.603 ms |
| 5,000 | unique target first | PASS | ~90.067 ms |

The <5s committed bounds are intentionally broad regression guards, not SLAs.

Temporal/conflict cases include:

- A→B→C meeting/status supersession;
- current retrieval resolves only C;
- historical retrieval retains A/B with superseded state;
- deletion of C does not silently resurrect obsolete A/B because their `valid_to` remains authoritative;
- a time-valid January query returns provider A while a later March query returns provider B;
- retention deletion removes memory from context, temporal results and graph;
- exact duplicates reuse the existing authoritative memory identifier.

## Permission / privacy qualification

NORMAL, SENSITIVE and SECRET behavior was exercised.

- unqualified direct `context()` is normal-only;
- explicit existing authorization may include sensitive/secret;
- hidden graph neighbors cannot leak via relationship counts or relationship expansion;
- reminder-linked context is normal-only unless an existing device has `memory:sensitive`;
- owner reminder API uses trusted device/session authorization and does not expose unauthenticated inspection;
- operational reminder audit stores IDs/state/action/safe metadata rather than reminder/private text.

## Reminder architecture audited

Two pre-existing paths existed:

1. P4 `EverydayIntelligence` with richer goals/reminders/follow-ups/commitments/briefing persistence;
2. legacy `tools/reminders.py` writing a simpler `MemoryStore.tasks` row.

The correct authority for daily-use lifecycle is now the existing P4 `everyday_items` store. No third reminder database/state machine was created. In the full runtime the existing reminder tool delegates dynamically to P4; the legacy tasks-table path remains only for minimal/embedded runtimes where P4 is absent.

## Reminder lifecycle implementation

Durable states:

`created → scheduled → due → surfaced`

with supported transitions to/from active state as appropriate:

- `snoozed`;
- rescheduled back to `scheduled`;
- `completed`;
- `dismissed`;
- `cancelled`;
- `superseded`.

Existing rows marked `open` or `pending` migrate additively to `created` or `scheduled`. Existing callers using `items(status='open')` receive an active-state compatibility view.

The P4 SQLite store adds lifecycle columns plus `everyday_audit`. There is no global schema-version change; W7/W8 schema remains 73.

## Due-time behavior

The due engine uses an injectable clock, avoiding flaky wall-clock tests. Qualified behavior includes:

- exact aware date/time;
- date-only due in the item's timezone;
- overdue classification;
- snooze;
- reschedule;
- cancellation;
- completion;
- dismissal;
- restart while due/surfaced;
- idempotent surfacing through persisted `last_surface_key` + `surface_count`.

No existing recurring-reminder contract was found, so this tranche did not invent an incompatible recurrence model.

## Follow-up / forgotten-item behavior

Follow-ups can carry explicit evidence and references to already-existing memory IDs. Invalid/missing memory IDs are discarded; relationships are not inferred/fabricated. Deleting related memory immediately removes it from reminder context because there is no derived copy.

`forgotten()` now selects evidence-bearing deterministic state:

- unresolved commitment/follow-up with no future due time;
- due/overdue commitment/follow-up;
- explicit unscheduled commitment/follow-up.

It excludes future scheduled, completed, dismissed, cancelled and superseded items, and suppresses normalized duplicates.

Fixed benchmark expected positives:

- overdue John follow-up;
- due proposal commitment;
- explicit unscheduled promise.

Negatives include future, completed, cancelled, superseded, irrelevant goal and duplicate commitment.

Result: **precision 1.0; recall 1.0; false positives 0; false negatives 0** on this deterministic fixture. This is not a claim of real-world natural-language extraction accuracy.

## Daily briefing

Briefing now combines:

- current permission-filtered Second Brain memory;
- top open priorities;
- needs-attention items;
- evidence-based possible forgotten commitments;
- today's commitments;
- overdue follow-ups;
- connected-service state.

This does not redesign Home/AI Core and does not turn Home into a dashboard.

## Delivery boundary

Repository evidence proves lifecycle logic: create/schedule/due/surface/snooze/reschedule/complete/cancel/persist/idempotency. It does **not** prove real notification delivery.

- LIVE DELIVERY VERIFIED: **NO**
- PHYSICAL IPHONE PUSH VERIFIED: **NO**
- PHYSICAL DEVICE VERIFIED: **NO**
- PRODUCTION VERIFIED: **NO**

No real iPhone push, APNs delivery, live email/calendar follow-up or production endpoint was exercised.

## Performance qualification

Qualification-environment measurements:

- 100-memory retrieval: ~3.943 ms;
- 1,000-memory retrieval: ~18.603 ms;
- 5,000-memory retrieval: ~90.067 ms;
- 5,000 future reminder due-evaluation: ~24.772 ms, correctly 0 due.

These are diagnostic qualification measurements and not production promises.

## Focused tests

Focused deterministic suites:

- `tests/test_p5_retrieval_qualification.py`
- `tests/test_p4_reminder_lifecycle.py`
- `tests/test_p4_proactive_precision_recall.py`
- `tests/test_p4_reminder_tool_delegation.py`

Result: **25 collected, 25 passed, 0 failed, 0 warnings in 0.96s**.

## Full implementation validation

Final implementation SHA: `14f0d5dbe532d5edf7ec910270d0d9114f5f9d8b`.

Full repository CI: **997 passed, 0 failed, 8 warnings in 30.64s**.

- pip check: PASS
- compileall: PASS
- pip-audit: PASS
- isolated encrypted backup/restore: PASS
- 45-second soak: PASS

Exact-head workflows:

| Workflow | Run | Run ID | Result |
| --- | ---: | ---: | --- |
| CI | #1065 | `34984377146` | PASS |
| Reliability and Security | #247 | `34984377349` | PASS |
| P3 iPhone PWA | #204 | `34984377120` | PASS |
| Android Instrumentation | #246 | `34984377166` | PASS |
| Package Validation | #246 | `34984377239` | PASS |
| iOS Companion | #228 | `34984377173` | PASS |

Gate: **6/6 PASS**. P3 was legitimately triggered by the new trusted API mount in `server/cloud_app.py`; no cosmetic P3 file change was created.

## Implementation diff

`4985dd014ec8c29c9f90c2dba8f153ea8a5bb969` → `14f0d5dbe532d5edf7ec910270d0d9114f5f9d8b`

- commits: 1
- files: 10
- additions: 1,557
- deletions: 119
- dependency changes: none
- production/Railway/OAuth/provider/signing changes: none
- W7/W8/P6 implementation changes: none
- global schema version: 73 unchanged
- P4 local storage: additive lifecycle/audit extension only

## Final implementation classification

- IMPLEMENTED: **YES**
- INTEGRATED: **YES**
- AUTOMATED VALIDATED: **YES**
- LIVE DELIVERY VERIFIED: **NO**
- PHYSICAL VERIFIED: **NO**
- PRODUCTION VERIFIED: **NO**

## Next dependency-order recommendation

After this tranche's documentation/evidence head passes its own exact-head gate, the next strongest unblocked candidate remains **P6 Governed Delegation Integration**, subject to a fresh repository audit before coding.

The intended composition is:

`PersonalOperations → existing AgentExecutor / AutomationEngine → frozen W7 transaction / approval / verification / recovery authority`

It must not create a new action authority and must not bypass P3 activation requirements.
