# Database recovery contract

This is not a stage freeze. Stage 12 is not open. There is no unified database rollback.

Stage 10 and Stage 11 already recorded that fact. This note classifies the stores that exist. It does not add a down migration or a single rollback command.

## Classes

| Class | Meaning |
|---|---|
| schema rollback | Not supported for any store. Nothing lowers `PRAGMA user_version` or drops a table to return a schema to an older process. |
| forward-fix | Every store. A newer process may add a missing table or column, or raise `user_version` when it is lower than the code. An older process opening a newer file is unsupported. |
| transaction | A failed write rolls back that connection's transaction. It does not roll back another database, a file already replaced, or a tool effect that already happened. |
| backup | An encrypted AES-256-GCM archive may contain the file. Restore replaces the current file with the archived bytes. `vault.json`, `.env`, and `secrets.json` are not archived. |
| unrestorable security state | The file may be inside the archive. Restore skips it. The current file stays, and a missing file is not created from the archive. The match is the basename, including a copy in a subdirectory. |

If restore fails after it has replaced a file, those replaced files are put back from the pre-restore copies. That undoes the interrupted restore. It is not a schema rollback.

## Unrestorable security state

A backup must not resurrect a revoked device, a session, an approval epoch, the emergency-stop flag, an operator policy, an operator transaction, an owner credential, or a connector grant.

- `devices.sqlite3`
- `pwa-sessions.sqlite3`
- `cloud-sessions.sqlite3`
- `trusted-actions.sqlite3`
- `runtime-controls.sqlite3`
- `operator-policies.sqlite3`
- `operator-transactions.sqlite3`
- `owner-access.sqlite3`
- `connectors.sqlite3`

## Backup restore

These stores are replaced from the archive. Restoring `trusted-action-audit.sqlite3` restores the audit text only. It does not restore authority, because the security stores above are skipped.

`assistant.sqlite3`, `vectors.sqlite3`, `memory-candidates.sqlite3`, `knowledge.sqlite3`, `continuity.sqlite3`, `proactive.sqlite3`, `turn-runtime.sqlite3`, `automations.sqlite3`, `workflow-budgets.sqlite3`, `voice-qualification.sqlite3`, `p3-qualification.sqlite3`, `capability-benchmark.sqlite3`, `model-dialogue-evaluation.sqlite3`, `trusted-action-audit.sqlite3`, `everyday.sqlite3`, `life-graph.sqlite3`, `operations.sqlite3`, `world.sqlite3`, `autonomy.sqlite3`.

Knowledge object files under the data directory follow the same backup rules as other non-database files. They are not a second schema.

## What a caller cannot do

The caller cannot ask restore to put a security store back. The caller cannot request a schema rollback. A transaction rollback in one store does not undo another store.
