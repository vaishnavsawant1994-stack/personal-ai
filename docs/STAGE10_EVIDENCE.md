# Stage 10 evidence — not a freeze

**Status:** Open. This file is not a Stage 10 freeze and not a V1 release.  
**Entry contract:** `docs/STAGE10_CONTRACT.md`  
**Stage 9 source:** `ddd53d17d60db2e5e5438cf29e2d704a9ba69af0`

The candidate SHA is the commit that adds `requirements-3.12.lock` and this record. It is not qualified until its own six pull-request families succeed. Do not treat this page as that result.

## Python lock

| Fact | Value |
| --- | --- |
| Interpreter | CPython 3.12.14 |
| Resolver | uv 0.12.19, then `python -m pip freeze` |
| `pip check` | no broken requirements |
| `requirements.txt` sha256 | `24c0a234837bdc15b82e14263905337dc8ec857ee095570046873ea2869bd4fb` |
| `requirements-3.12.lock` sha256 | `50c7306b260a58fed84d8d6afb4a64bb566b7d7e2e04c3c1ec9b575b9b1ae361` |
| Second environment | A new 3.12.14 venv installed from the lock with pip. `pip check` passed. `pip freeze` matched the lock pins. |

`requirements.txt` ranges were not edited. The six Python-using families install `requirements-3.12.lock` from the commit that changes those workflows. `01a67a2` contains the lock but its CI still installed the ranges, so it is not the Stage 10 freeze.

## Other inputs

| Input | Result |
| --- | --- |
| Node | No `package.json`. `pwa/` is static. Nothing to lock. |
| Android direct deps | Pinned in `android-companion/app/build.gradle.kts` and plugin versions in `build.gradle.kts`. |
| Android transitives | No `gradle.lockfile`. Still uncontrolled. Not called locked. |
| iOS third-party packages | None in `ios-companion/project.yml`. |
| GitHub Actions | Still `@v4` / `@v5` tags. Identified, not re-pinned. |
| Unified database rollback | Unsupported. Not invented. |
| Clean sqlite startup | `tests/test_stage10_exact_source.py` opens the Stage 9 stores on an empty directory and reopens them. Emergency Stop survives that restart. |

## Artifacts

Installer checksums are not in this file. They belong to the candidate SHA's Package Validation run. Until those files are hashed from that run, installer provenance is **UNQUALIFIED**. Simulator success is not a physical device.

## Still deferred

`GET /workflows`, `GET /capabilities/api/status`, `POST /iphone/api/logout`, C6, F4, and all Stage 11 physical proof.

## Not claimed

No merge. `main` unchanged. Stage 11 not open. Not production-ready.
