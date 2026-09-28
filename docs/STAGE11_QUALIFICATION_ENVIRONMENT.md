# Stage 11 qualification environment

Not production. Not Stage 12. Not a Stage 11 freeze. Not the public p2 site.

The qualified post-Stage-10 recovery checkpoint stays `b22fbb58179aa3f1974ded4cb4c881f92f972d31`. Procedure preparation stays `d45212499497c0662c147f7b021c2ac7fa07fc13`. Neither SHA is replaced by a later note.

## What runs

`python -m qualification.serve_stage11` starts `server.cloud_app` only when:

- the git tree matches `HEAD`
- `HEAD` is a 40-character SHA
- the bind host is not `personal-ai-runtime-production.up.railway.app`
- the data directory is not `~/.personal_ai`

The process sets `PERSONAL_AI_ENVIRONMENT=stage11-qualification` and `PERSONAL_AI_SOURCE_SHA` to that exact `HEAD`. It then refuses to listen unless `PERSONAL_AI_DATA_DIR` is on a non-ephemeral mount beneath `PERSONAL_AI_QUALIFICATION_DURABLE_ROOT`. `/tmp`, the default `~/.personal_ai` directory, the public p2 host, and a `trycloudflare.com` host are refused.

`GET /iphone/api/stage11/identity` returns the SHA. `production` stays false. `durable` is true only when that mount proof succeeds. `ready_for_physical` is true only when the mount proof, a model credential in the environment, and `PERSONAL_AI_QUALIFICATION_PUBLIC_HOST` are all present. The host must not be the public p2 site or a quick tunnel. The payload never includes the model credential. `rows_passed` stays 0. This process does not write `docs/stage11_register.json`.

`87d86d9eb74b50ed8f307ad8b90aefdafc4449bc` is the exact-head 6/6 software candidate. It is not a Stage 11 freeze. A later change that only records or tightens this gate does not move that candidate and does not pass a physical row.

## What an iPhone session may use

Safari can open `/iphone/` on this process. An Apple Developer account is not required for that path. It is required for a signed native companion, which this environment does not provide.

The old site `https://personal-ai-runtime-production.up.railway.app/iphone/` is a different host. A visit there is not evidence for this SHA.

## First batch, still pending

Do not mark these passed from this document. Run them on a physical iPhone against the SHA from `/iphone/api/stage11/identity`, one packet each:

1. `S11-IOS-01`
2. `S11-VOICE-01`
3. `S11-FAIL-01`, then `S11-FAIL-03`
4. `S11-FAIL-02`
5. `S11-FAIL-04`
6. `S11-FAIL-05`
7. `S11-FAIL-07`

Stop if `S11-IOS-01` fails. Keep the evidence. Do not continue on a broken trusted-device journey.

`S11-OAUTH-01` and `S11-FAIL-06` wait for a real provider login on this same SHA. `S11-ESTOP-01`, `S11-FAIL-08`, and `S11-FAIL-10` wait for a live stop on this runtime. `S11-ANDROID-01` and `S11-FAIL-09` stay pending until another physical handset exists.

PR #2 stays a draft. `main` stays `c1cd8b7f2e507befb7f4cad37de6208d75a75a72`.
