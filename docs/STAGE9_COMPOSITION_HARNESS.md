# Stage 9 — Composition Harness (minimum scenarios)

These scenarios prove authorities compose; they are not a substitute for Stage 8 unit hostility.

| ID | Scenario | Pass criteria |
| --- | --- | --- |
| H1 | E-stop on → cloud command | HTTP 423 (or project-equivalent); no tool side effect |
| H2 | E-stop on → running workflow | status `recovery_required`; no further tool dispatch |
| H3 | Revoke source device during handoff | handoff fails closed; target not activated on stolen authority |
| H4 | Connector Knowledge without `knowledge:write` | 403; zero Knowledge rows/objects |
| H5 | Connector Knowledge `approved=false` | 409; zero durable side effects |
| H6 | Private ingest without `knowledge:private` | 403; zero durable side effects |
| H7 | Workflow runs with missing `run_binding` | 503 (fail closed); no row dump |
| H8 | Default search/Memory path | no `access_class=private` hits |
| H9 | Planned P10/workflow tool without approval when required | no side effect; approval or deny visible |
| H10 | Hostile restore parent-symlink swap | BackupError; no files created outside data root |
| H11 | Activity stream after verified=false tool | not presented as pure success |
| H12 | Security epoch advance | prior approval tickets unusable for dispatch |

Automate H1–H12 under `tests/test_stage9_composition_*.py` as Stage 9 proceeds. Prefer exact-head green over expanding scope.
