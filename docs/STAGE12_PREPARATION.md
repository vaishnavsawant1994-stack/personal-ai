# Stage 12 preparation

**Stage 12 is not open.** This page is not a Stage 12 freeze, not a production deploy, and not a Stage 11 pass.

Stage 8 stays `b17c5051772b5e82b7a6a208903bb0300bf1e405`. Stage 9 stays `ddd53d17d60db2e5e5438cf29e2d704a9ba69af0`. Stage 10 stays `cd558936276aece705fa46032e3bab6453c7f014`. The current Stage 11 software candidate is `93d26a5de3e928a61866d2d78728ec33270120d9`. `08b2616c11d1433760eb711db4ca7f82e5a01a2c` is the earlier candidate. A note that only records a green run does not move the candidate. `main` stays `c1cd8b7f2e507befb7f4cad37de6208d75a75a72`. PR #2 stays a draft.

Nothing below was executed against a live production or qualification host.

## Already true in the repository

| Item | State |
|---|---|
| Database recovery classes | Written and tested. No schema rollback and no single rollback command. Nine security stores are not restored. |
| Emergency Stop authority | Server-side tests already keep the stop across a fresh cloud session and a restarted future-intelligence process. That is not `S11-ESTOP-01`. |
| OAuth token handling | Connector secrets go through the encrypted vault. Local revoke is recorded even when the provider call fails. A real owner login was not performed. |
| Qualification process | `python -m qualification.serve_stage11` refuses the public p2 host, a `trycloudflare.com` host, `~/.personal_ai`, and a data directory that is not on a non-ephemeral mount. `production` stays false. |

## Not run

| Item | State |
|---|---|
| Production compute, network, TLS, and domain | NOT RUN |
| Qualification hostname and persistent volume | NOT RUN. No owner disk and no DNS name were available. |
| Model and OAuth secrets in a deployment secret store | NOT RUN. No credential was written to git. |
| Monitoring alerts and paging | NOT RUN |
| Backup job on a live host | NOT RUN. The backup code is not a drill. |
| Disaster-recovery reconstruct on a disposable cloud | NOT RUN |
| Retention, export, and delete drill | NOT RUN |
| SBOM or signed release | NOT RUN |
| Incident-response drill | NOT RUN |
| Exact-source production deploy and rollback drill | NOT RUN |

## Incident notes for later, not a drill

When Stage 12 is actually opened, a compromised device is revoked in the device registry and its PWA sessions are revoked. A compromised connector grant is revoked locally even if the provider is unreachable. A restored backup must not bring those grants, sessions, or the Emergency Stop flag back. Those rules are already what the code and the recovery contract say. They were not replayed on a production host for this page.

## Qualification deploy contract, not a running service

A future qualification host, separate from `personal-ai-runtime-production.up.railway.app`, has to set:

- `PERSONAL_AI_ENVIRONMENT=stage11-qualification`
- `PERSONAL_AI_PRODUCTION=false`
- `PERSONAL_AI_SOURCE_SHA` to the exact 40-character commit that is running
- `PERSONAL_AI_QUALIFICATION_DURABLE_ROOT` to a mounted data disk, not `/` and not `/tmp`
- `PERSONAL_AI_DATA_DIR` beneath that root
- `PERSONAL_AI_QUALIFICATION_PUBLIC_HOST` to the stable hostname
- the model credential and enrollment code only in the secret store

`GET /iphone/api/stage11/identity` may report `ready_for_physical` only after the mount, the model credential, and that hostname are all present. `rows_passed` stays 0 until a real Stage 11 packet is accepted. This repository does not have that host.
