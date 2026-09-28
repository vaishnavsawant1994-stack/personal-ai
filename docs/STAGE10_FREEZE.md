# Stage 10 freeze

**Freeze SHA:** `cd558936276aece705fa46032e3bab6453c7f014`  
**Date:** 28 September 2026  
**This note does not move the freeze.** A later commit that only records this page is not a new Stage 10 freeze.

Stage 9 stays `ddd53d17d60db2e5e5438cf29e2d704a9ba69af0`. Stage 8 stays `b17c5051772b5e82b7a6a208903bb0300bf1e405`.

`01a67a2` is not the freeze: its CI still installed floating ranges. `e326a45` is not the freeze: Windows package install failed because `uvloop` does not support Windows.

## Exact-head 6/6

| Family | Run | Conclusion |
| --- | --- | --- |
| CI | [36416991305](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36416991305) | success |
| Reliability and Security | [36416991319](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36416991319) | success |
| P3 iPhone PWA | [36416991300](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36416991300) | success |
| Android Instrumentation | [36416991404](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36416991404) | success |
| Package Validation | [36416991349](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36416991349) | success |
| iOS Companion | [36416991318](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36416991318) | success |

Package jobs on `ubuntu-latest`, `windows-latest`, and `macos-latest` all succeeded. CI, Reliability, P3, and Package installed `requirements-3.12.lock`.

## Lock and artifacts from that SHA

| Item | sha256 |
| --- | --- |
| `requirements.txt` | `24c0a234837bdc15b82e14263905337dc8ec857ee095570046873ea2869bd4fb` |
| `requirements-3.12.lock` | `67e61b0895b6925666bcc65007d23d3a43bc1474f40534b4dd48a3910e7ed13d` |
| `personal-ai_0.6.0_amd64.deb` | `f0a7925c1753a0ba1cb786630aabce94a754dec62df624216d239ef1494f5a5c` |
| `personal-ai-0.6.0-win64.msi` | `ad96fdcfe46119e43b4d8a73d642a8c510f097fbf75f3888a97f7e3f45ad98dc` |
| `PersonalAI.dmg` | `d359af30912f5e7609ae3f04ad0b303681cf56617552dcfc9c227de0eacb642c` |

Interpreter that produced the lock: CPython 3.12.14. `uvloop==0.22.1` is installed only when `sys_platform != "win32"`.

Entry contract: `docs/STAGE10_CONTRACT.md` (`0b8597b`). Clean-data restart: `tests/test_stage10_exact_source.py`.

## Still not locked or not closed

| Item | State |
| --- | --- |
| Android Maven transitives | No `gradle.lockfile`. Direct versions are pinned. Not called locked. |
| GitHub Actions | Still major tags. Identified, not re-pinned. |
| Unified database rollback | Unsupported. Not invented. |
| GET /workflows, capability status, cookie-only logout, C6, F4 | Still deferred from Stage 9 and Stage 8. |
| Physical devices, OAuth, microphone, live Emergency Stop | Not claimed. Stage 11. |

## What this freeze does not do

PR #2 stays a draft. `main` is not updated. Stage 11 is not started. Stage 12 is not started. Version string `0.6.0` is not a production release. Not production-ready.
