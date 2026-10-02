# Dual Cloud Installation Operations

## Installation boundaries

| Setting | Railway | Render |
|---|---|---|
| `PERSONAL_AI_INSTANCE_ID` | `railway-primary` | `render-independent` |
| Data root | Railway's existing `/data` volume | A separate Render persistent disk mounted at `/data` |
| Data directory | Existing `PERSONAL_AI_DATA_DIR` value, beneath `/data` | `/data/.personal_ai` |
| Root/vault key | Keep the existing Railway secret unchanged | Generate and store a separate Render secret |
| Owner/session/device data | Railway volume | Render volume, enrolled independently |
| External automation during qualification | Existing configuration; do not change without review | `PERSONAL_AI_AUTOMATION_EXECUTION_ENABLED=false` |

Do not copy database files, vault files, session cookies, device records, upload
directories, or backups between these installations. Google may identify the
same human owner, but each service must use its own app cookies and data root.

## Identity marker

On the first hosted startup after this release, the service writes
`.personal-ai-instance.json` into its data directory. It contains only the
installation ID and creation time. Creation does not rewrite existing database
or vault contents. Later starts require the configured ID to match the marker;
a mismatch or unreadable marker stops startup and requires operator review.
Never resolve a mismatch by deleting the marker or copying it from the other
installation.

Set `PERSONAL_AI_INSTANCE_ID` before deploying this release. Railway's existing
data is currently unmarked; first binding will add the Railway label in place
after the durable mount check. Keep its existing root key and data path intact.

## Storage and cost gate

Render's current mobile preview uses an ephemeral filesystem. The cloud app
requires a verified persistent mount beneath `PERSONAL_AI_DURABLE_ROOT`, so this
release must not be deployed to the existing free service until an appropriately
priced persistent disk is approved and attached. Use one service instance: a
Render disk is local to one instance and Render disables zero-downtime deploys
when a disk is attached. Start with the smallest supported disk; increasing its
size later is possible, while decreasing it is not.

For both services configure `PERSONAL_AI_DURABLE_ROOT=/data` and ensure
`PERSONAL_AI_DATA_DIR` resolves under the actual mounted volume. Keep temporary
caches outside durable data. Verify a marker and database survive both a process
restart and a new deploy before treating the service as persistent.

## Automation isolation

`PERSONAL_AI_AUTOMATION_EXECUTION_ENABLED=false` prevents scheduler startup,
event-triggered workflow runs, manual workflow execution, approvals that would
resume a workflow, and in-flight workflow continuations on that service. It
does not delete workflows or their records. Attempting to run or approve a
workflow returns a conflict response that identifies the disabled state.
Render must remain disabled during qualification. Do not enable external
automation on both clouds until each integration's credentials and intended
real-world effects have been reviewed with the owner.

## Release process

1. Develop on a feature branch and run CI, security, PWA, and qualification jobs.
2. Deploy a tested immutable SHA to Render only after persistent storage and
   owner authentication are configured. Keep automation execution disabled.
3. Complete browser checks and owner physical-iPhone acceptance.
4. Record the exact accepted SHA and evidence in the release manifest.
5. Separately authorize deployment of that exact SHA to each service. Never
   point Railway production at a development branch or deploy a moving branch
   as a qualified release.
6. Verify each service's health, instance ID, storage marker, auth, data
   persistence, and rollback target independently.

Before production deployment of this identity change, confirm the existing
Railway volume path and keep a verified encrypted backup available. A failed
identity check should be resolved by restoring the correct service setting or
recovering that service's own data, never by exchanging IDs or data between
installations.

## Rollback and recovery

Roll back code to the last known-good deployment for that same service. Do not
roll back storage by deleting the identity marker or restoring another
installation's disk snapshot. Restore a service only from its own encrypted
backup, with that service's existing key material. Re-run SQLite integrity
checks and application health checks after restoration. Keep Railway and Render
running independently; there is no cross-instance synchronization or production
data cutover in this process.
