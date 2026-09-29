# Stage 11 evidence format

A pending row is not evidence. A pass or fail packet is one JSON object with these fields:

| Field | Required | Rule |
| --- | --- | --- |
| `case_id` | yes | One id from the Stage 11 matrix. |
| `verdict` | yes | `PASS`, `FAIL`, or `BLOCKED`. Pending values are the register default, not a submitted result. |
| `evidence_class` | yes | `real_device` or `production_like` only. |
| `form` | yes | `physical`. |
| `runner` | yes | The owner machine. `ubuntu-latest`, `macos-latest`, and `windows-latest` are rejected. |
| `source_sha` | yes | 40-character git SHA that was actually installed. |
| `captured_at` | yes | ISO-8601 timestamp from the run, including `T`. |
| `platform` | yes | For example `iPhone`, `Android`, or the provider name. |
| `os_version` | yes | The device or provider client version. |
| `device_id` | yes | UDID, serial, or provider subject. Not an emulator id. |
| `operation_id` | yes | The operation that was attempted. |
| `expected` | yes | The matrix expectation for that case. |
| `actual` | yes | What happened. Required for `FAIL` too. |
| `audit_ref` | yes | Log, screenshot archive, or audit id from that run. |
| `owner_attestation` | owner-gated cases | Must be `present`. |
| `owner_actor` | when attestation is present | Who completed the owner step. |

The collector rejects a packet whose text contains an emulator, simulator, or GitHub-hosted marker. Rejection leaves the row pending.

Current register: [stage11_register.json](stage11_register.json). `frozen` is false. No row has an actual result.
