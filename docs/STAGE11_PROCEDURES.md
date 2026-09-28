# Stage 11 procedures

These procedures stop at a real device or a real owner account. Do not fill a gap with CI, an emulator, or a simulator. A missing device stays `PENDING_PHYSICAL`. A missing owner login stays `PENDING_OWNER`.

Record every attempt with the evidence format in [STAGE11_EVIDENCE_FORMAT.md](STAGE11_EVIDENCE_FORMAT.md). A failed real attempt is `FAIL` or `BLOCKED`, then either a repair with a regression test or an explicit blocker. It is not a pass.

## S11-IOS-01 — iPhone

1. Install the exact source SHA on a physical iPhone. Record the UDID, model, and iOS version.
2. Authenticate as the owner and establish a trusted device.
3. Run a Conversation turn that reads Memory and Knowledge.
4. Run one connector action that the consent matrix allows.
5. Revoke that device.
6. Repeat the same call and prove it fails.

Stop here if the phone, signing team, or owner account is absent.

## S11-ANDROID-01 — Android

1. Install the exact source SHA on a physical Android phone. Confirm it is not an emulator.
2. Authenticate, grant the permissions the journey uses, and keep the session.
3. Hand off continuity to a second surface or back.
4. Revoke the device.
5. Prove the stale session cannot continue.

## S11-VOICE-01 — Microphone

1. Use a physical microphone, not a file and not a mocked stream.
2. Grant permission, capture, process, and receive a model response.
3. Interrupt or cancel the turn.
4. Activate Emergency Stop and prove the next capture does not run.

## S11-OAUTH-01 — Provider

1. Sign in to the real provider. Do not paste a fixture token.
2. Finish the callback and store the token.
3. Perform one permitted operation.
4. Revoke the provider.
5. Prove the stored credential fails closed.

Stop here if the owner will not complete the provider login. That is `PENDING_OWNER`.

## S11-ESTOP-01 — Live Emergency Stop

1. Start a real activity on the deployed owner runtime.
2. Activate Emergency Stop.
3. Prove a new execution is blocked.
4. Prove a queued or retried execution is blocked.
5. Restart the server. Prove it stays stopped.
6. Reset only through the explicit authorization path. Prove execution works again.

## Failure cases

| Id | What to do | Stop when |
| --- | --- | --- |
| `S11-FAIL-01` | Drop the network during a real operation. | No physical network path. |
| `S11-FAIL-02` | Background or kill the app mid-operation. | No physical handset. |
| `S11-FAIL-03` | Reconnect that phone and record resume or fail-closed. | No physical handset. |
| `S11-FAIL-04` | Replay a stale device session. | No physical session to stale. |
| `S11-FAIL-05` | Revoke the device while a call is active. | No physical handset. |
| `S11-FAIL-06` | Revoke the provider credential outside Personal AI. | Owner will not use the provider. |
| `S11-FAIL-07` | Deny or revoke microphone permission on the device. | No physical microphone. |
| `S11-FAIL-08` | Restart the owner server while Emergency Stop is on. | No owner server to restart. |
| `S11-FAIL-09` | Hand off between two real devices, including one revoked device. | Fewer than two real devices. |
| `S11-FAIL-10` | Activate Emergency Stop while an operation is in progress. | No physical operation to interrupt. |

Stage 9 restart tests are not a substitute for `S11-FAIL-08` or `S11-ESTOP-01`.
