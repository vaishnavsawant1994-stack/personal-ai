# Post-Stage-10 API hardening checkpoint

**Qualified SHA:** `a50bb56268261304ff02ce658a8b6a202a9ba51a`  
**Date:** 28 September 2026  
**This is not a Stage 8, 9, 10, or 11 freeze.** A later note that only records this page does not move the qualified SHA.

Stage 8 stays `b17c5051772b5e82b7a6a208903bb0300bf1e405`. Stage 9 stays `ddd53d17d60db2e5e5438cf29e2d704a9ba69af0`. Stage 10 stays `cd558936276aece705fa46032e3bab6453c7f014`.

## What this checkpoint is

The three API repairs on `a50bb56`: device-scoped `GET /workflows`, session-protected `GET /capabilities/api/status`, and iPhone logout that revokes that device and its server sessions. Hostile tests cover those boundaries. This does not pass any Stage 11 physical row.

## Exact-head 6/6

| Family | Run | Conclusion |
| --- | --- | --- |
| CI | [36423902907](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36423902907) | success |
| Reliability and Security | [36423902853](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36423902853) | success |
| P3 iPhone PWA | [36423902944](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36423902944) | success on rerun |
| Android Instrumentation | [36423902880](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36423902880) | success |
| Package Validation | [36423902927](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36423902927) | success |
| iOS Companion | [36423902800](https://github.com/vaishnavsawant1994-stack/personal-ai-snapshot-20260928/actions/runs/36423902800) | success |

The first P3 attempt on this same SHA failed during `pip install -r requirements-3.12.lock` with a PyPI read timeout for `click==8.5.0`. It did not reach the PWA tests. The failed job was rerun with no code change. The rerun installed the lock, ran the iPhone PWA tests, and passed.

## Not claimed

PR #2 stays a draft. `main` stays `c1cd8b7f2e507befb7f4cad37de6208d75a75a72`. Stage 11 rows stay pending. Stage 12 is not started. Not production-ready. The public `p2` site is not this SHA.
