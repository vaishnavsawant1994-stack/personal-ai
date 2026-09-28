# Personal AI — Capability Matrix Addendum (2026-09-14 W4 A-C)

This addendum records the current branch-only W4 batch without rewriting the historical baseline matrix.

| Capability | Status | Branch implementation/evidence | Remaining gate |
| --- | --- | --- | --- |
| Explainable Memory retrieval | QUALIFICATION | query-specific explanations, owner API and Memory inspection UI; sensitive/NEVER_STORE filtering; regression tests staged | exact-head full CI/security/client/package validation; durable-production qualification |
| Knowledge immutable version lineage | QUALIFICATION | additive schema migration, current/superseded versions, history, per-version/lineage deletion, restart and checksum-reversion tests staged | exact-head full validation; durable-production restart/redeploy proof |
| PDF page-level Knowledge provenance | QUALIFICATION | page-aware chunks/citations staged | exact-head validation and representative document qualification |
| Image/OCR ingestion | PARTIAL | bounded image formats/size/pixel checks, metadata stripping, provider contract, private-external fail-closed behavior and deterministic tests staged | approved real OCR provider plus representative real-document operational qualification |

The frozen Home V1 architecture is unchanged. Memory and Knowledge remain separate product domains.
