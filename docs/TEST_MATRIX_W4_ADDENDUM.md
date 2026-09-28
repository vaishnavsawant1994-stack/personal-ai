# Personal AI — Test Matrix Addendum (2026-09-14 W4 A-C)

The following tests are added for the current branch-only W4 A-C batch:

- `tests/test_explainable_memory.py`: real-selection explanations, historical/superseded state, sensitive/NEVER_STORE filtering, deleted-memory behavior.
- `tests/test_knowledge_versioning_ocr.py`: immutable versions, restart lineage, current-only retrieval, PDF page citations, deletion repair, OCR bounds, metadata stripping, private-external OCR rejection, repeated-checksum restart safety.
- `tests/test_memory_knowledge_inspection_api.py`: trusted-browser API access, pre-selection sensitivity filtering, owner-inspectable version history.

Focused isolated Knowledge versioning/OCR execution: 7 PASS.
Generated Python compilation: PASS.

Full repository pytest and every exact-head GitHub workflow remain mandatory before the batch can move from branch implementation to automated validation.
