# Stage 10 entry contract

**Status:** Entry contract only. This is not a Stage 10 freeze, not a V1 release, and not implementation evidence.  
**Date:** 28 September 2026  
**Base:** Stage 9 freeze `ddd53d17d60db2e5e5438cf29e2d704a9ba69af0`

Stage 10 starts here. No Stage 10 code, lock, or evidence written before this contract counts.

## Immutable boundary

| Item | Value |
| --- | --- |
| Repository | `vaishnavsawant1994-stack/personal-ai-snapshot-20260928` |
| Stage 8 freeze | `b17c5051772b5e82b7a6a208903bb0300bf1e405` |
| Stage 9 freeze / exact source at entry | `ddd53d17d60db2e5e5438cf29e2d704a9ba69af0` |
| Later record commit | `83302e4d3ec642e69cbd38a47ec891958a039882` is docs only (`STAGE9_FREEZE.md`, `STAGE9_STATUS.md`). It is not the V1 source. |
| `main` | `c1cd8b7f2e507befb7f4cad37de6208d75a75a72` — do not move |
| PR #2 | Stays draft. Do not merge. |

`git diff ddd53d1..83302e4` is those two docs. Application source at entry is the Stage 9 freeze.

## What a V1 candidate is

One later git SHA, descendant of this contract, that still contains the Stage 9 tree and adds only Stage 10 deliverables:

1. This contract.
2. A CPython **3.12** lock of `requirements.txt`, hash recorded in the evidence manifest.
3. The evidence manifest.
4. Tests or scripts that check the lock and a clean data directory, if they do not change runtime behavior.

That SHA is not a Stage 10 freeze until its own six pull-request families are success. A later note may record the freeze. The note does not replace the qualified SHA.

Until that SHA exists, Stage 10 is open.

## Entry inputs (measured on `ddd53d1`)

| Input | State at entry |
| --- | --- |
| `requirements.txt` sha256 | `24c0a234837bdc15b82e14263905337dc8ec857ee095570046873ea2869bd4fb` |
| `pyproject.toml` sha256 | `785f5a227ed713967d68582dc9e949803adc743d87cb394e147d31e6b890f08e` |
| Project version string | `0.6.0` in `pyproject.toml`. Not a V1 claim. |
| Python | `requires-python >=3.11`. CI and package jobs use **3.12**. |
| Lockfile | **None.** Ranges such as `fastapi>=0.116,<1` are floating. This is the dependency gap Stage 10 must close. |
| Node | No `package.json`. `pwa/` is static. No npm build. |
| Android | `android-companion/`, Gradle **8.9**, Java **17**, emulator API **35**. No Gradle lockfile. |
| iOS | `ios-companion/project.yml`, XcodeGen, simulator, `CODE_SIGNING_ALLOWED=NO`. No Podfile. Signing is not this stage. |
| Database | No Alembic tree. Schemas are `CREATE TABLE IF NOT EXISTS` in application modules (41 modules at entry). There is no single migration runner and no single rollback command. |
| Installers | `packaging/build_installer.py`. CI `package.yml` expects `dist/*.deb`, `dist/*.dmg`, `dist/*.msi`. |
| CI actions | `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`, `actions/setup-java@v5`, `gradle/actions/setup-gradle@v4`. Major tags, not commit-pinned. |
| Runners | `ubuntu-latest`, `windows-latest`, `macos-latest`. Floating images. |

## Configuration assumptions

- No production secrets in the tree.
- Cloud runtime defaults off (`cloud_runtime_enabled` is false).
- A clean data directory must start by creating its own sqlite files. Existing user data must not need an undocumented manual repair for the stores Stage 9 already restarts.
- Unified database rollback is **not supported** at entry. Stage 10 must not invent one. Record it as unsupported.

## Required evidence manifest

The manifest names:

- candidate SHA and Stage 9 SHA `ddd53d1`
- `requirements.txt` sha256 and lock sha256
- interpreter version that produced the lock (must be 3.12)
- workflow run IDs for the six families on that candidate
- installer or mobile artifact names and checksums, or `UNQUALIFIED` with the reason
- the three Stage 9 gaps plus C6 and F4, still deferred
- environmental assumptions, including floating runner images

## Six families that must be green on the candidate

CI, Reliability and Security, P3 iPhone PWA, Android Instrumentation, Package Validation, iOS Companion. Push-event runs are not a seventh family.

## Exit

Stage 10 freezes only after items 2–8 in the stage sequence are done on one SHA and that SHA is exact-head 6/6. Then a record commit may name it. Stage 11 stays closed. Production readiness is not claimed.

## Non-goals

- Do not merge PR #2.
- Do not edit Stage 8 or Stage 9 freeze SHAs.
- Do not relabel `GET /workflows`, `GET /capabilities/api/status`, `POST /iphone/api/logout`, C6, or F4 as solved.
- Do not describe simulator, mock, or CI results as a physical iPhone, Android phone, microphone, OAuth provider, or live Emergency Stop.
- Do not call the product production-ready.
