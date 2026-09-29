# Stage 9 — Entrypoint Census Template

Copy rows as routes are inventoried. Status: `canonical` | `proxy` | `delete` | `surface-specific-ok` | `gap`.

## Control HTTP (`server/api.py`)

| Route | Method | Auth | Scopes | Authorities touched | Status | Test ref |
| --- | --- | --- | --- | --- | --- | --- |
| `/health` | GET | none | — | models status | surface-specific-ok | |
| `/pair/start` | POST | loopback | — | pairing | canonical | |
| `/pair/confirm` | POST | pairing token | — | devices.registry | canonical | |
| `/command` | POST | bearer + device | `ai:chat` | executor | canonical | |
| `/continuity/resume` | POST | bearer + device | `ai:chat` | continuity | canonical | |
| `/continuity/sync` | GET | bearer + device | `ai:chat` | continuity | canonical | |
| `/continuity/append` | POST | bearer + device | `ai:chat` | continuity | canonical | |
| `/continuity/context` | POST | bearer + device | `ai:chat` | continuity | canonical | |
| `/continuity/handoff` | POST | bearer + device | `ai:chat` (+ target) | continuity, registry | canonical | Stage-8 handoff |
| `/workflows` | GET | bearer + device | `workflow:read` | automation | gap (filter?) | |
| `/workflows/runs` | GET | bearer + device | `workflow:read` | automation + run_binding | canonical | Stage-8 binding |
| `/workflows/create` | POST | bearer + device | `workflow:write` | automation | canonical | |
| `/workflows/run` | POST | bearer + device | `workflow:write` | automation | canonical | |
| `/workflows/pause` | POST | bearer + device | `workflow:write` | automation | canonical | |
| `/workflows/approval` | POST | bearer + device | `workflow:approve` | automation, approvals | canonical | |
| `/cloud/session` | POST | device token | — | cloud sessions | canonical | |
| `/cloud/command` | POST | cloud session | `ai:chat` | relay, E-stop | canonical | Stage-8 E-stop |
| `/cloud/emergency-stop` | POST | owner key | — | E-stop | canonical | |
| `/cloud/approval` | POST | cloud session | `approval:write` | approvals | canonical | |
| `/device/ws/{id}` | WS | bearer + device | `ai:chat` | gateway, continuity | canonical | revalidate loop |
| `/benchmark` | GET | bearer + device | `qualification:read` | benchmark | canonical | |
| `/dashboard-ui` | GET | loopback | — | dashboard | surface-specific-ok | |

## Connector / PWA API

| Route | Method | Auth | Scopes | Authorities touched | Status | Test ref |
| --- | --- | --- | --- | --- | --- | --- |
| `/iphone/api/connectors` | GET | cookie + session | `device:read` | integrations | canonical | |
| `/iphone/api/connectors/{id}/oauth/start` | POST | cookie + session | `device:admin` | oauth | canonical | |
| `/iphone/api/connectors/drive/files/{id}/knowledge` | POST | cookie + session | `knowledge:write` (+ private) | Knowledge, connector | canonical | Stage-8 connector Knowledge |
| `/iphone/api/connectors/sheets/{id}/knowledge` | POST | cookie + session | `knowledge:write` (+ private) | Knowledge, connector | gap (parity tests) | |

## Tools / desktop operators

| Tool / entry | Auth path | Scopes / policy | Status | Test ref |
| --- | --- | --- | --- | --- |
| W7 tool dispatch | executor + approvals | per-tool policy | canonical | |
| Legacy web open | tools.web | URL allowlist | canonical | Stage-8 URL |
| Browser operator | browser/* | policy gateway | gap | |
| Backup create/restore | recovery.backup | owner recovery UX | canonical | Stage-8 TOCTOU |

## Companions

| Client | Consequential calls | Min version policy | Status |
| --- | --- | --- | --- |
| Android | command, continuity, approvals | gap | |
| iOS | command, continuity, push | gap | |
| Web companion | status, limited actions | gap | |

Fill remaining rows during WP2. Any `gap` blocks Stage 9 exit unless explicitly deferred.
