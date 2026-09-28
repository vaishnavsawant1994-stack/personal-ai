# Stage 11 device and provider matrix

Not a freeze. Every row is pending. CI and simulators are not listed as passes.

| Id | Journey | Status | Expected |
| --- | --- | --- | --- |
| `S11-IOS-01` | iPhone trusted-device journey | `PENDING_PHYSICAL+PENDING_OWNER` | Authenticate, establish a trusted device, use Conversation and Memory/Knowledge, use a connector, revoke the device, and prove access fails. |
| `S11-ANDROID-01` | Android trusted-device journey | `PENDING_PHYSICAL+PENDING_OWNER` | Authenticate, grant permissions, keep a session, hand off continuity, revoke the device, and prove the stale session cannot continue. |
| `S11-VOICE-01` | Physical microphone journey | `PENDING_PHYSICAL` | Capture from a physical microphone, honor permission, process, call the model, speak a response, cancel on interruption, and honor Emergency Stop. |
| `S11-OAUTH-01` | Real provider login | `PENDING_OWNER` | Complete a real provider login and callback, store the token, perform one permitted operation, revoke the provider, and prove the stale credential fails closed. |
| `S11-ESTOP-01` | Live Emergency Stop cycle | `PENDING_PHYSICAL` | Start a real activity, activate Emergency Stop, block new work, block queued or retried work, restart, confirm it stays stopped, then reset only with an explicit authorization and confirm execution returns. |
| `S11-FAIL-01` | Network disappears during execution | `PENDING_PHYSICAL` | Drop the network during a real operation and record whether the operation fails closed and what is retried after reconnect. |
| `S11-FAIL-02` | App backgrounded or killed | `PENDING_PHYSICAL` | Background or kill the app during a real operation and record the recovered state. No silent success. |
| `S11-FAIL-03` | Phone reconnects | `PENDING_PHYSICAL` | Reconnect a real phone after a drop and record whether the session resumes or fails closed. |
| `S11-FAIL-04` | Stale session reused | `PENDING_PHYSICAL` | Reuse a stale device session and prove it is rejected. |
| `S11-FAIL-05` | Device revoked while active | `PENDING_PHYSICAL` | Revoke a device during an active real session and prove later calls fail. |
| `S11-FAIL-06` | Provider credential revoked externally | `PENDING_OWNER` | Revoke the provider credential outside Personal AI and prove the next call fails closed. |
| `S11-FAIL-07` | Microphone permission denied or revoked | `PENDING_PHYSICAL` | Deny or revoke microphone permission on a real device and prove capture does not proceed. |
| `S11-FAIL-08` | Server restarted while stopped | `PENDING_PHYSICAL+PENDING_OWNER` | Restart the owner server while Emergency Stop is on and prove the stop is still on after restart. |
| `S11-FAIL-09` | Two-device handoff | `PENDING_PHYSICAL+PENDING_OWNER` | Hand off between two real devices and record which session survives. A revoked device must not continue. |
| `S11-FAIL-10` | Emergency Stop during an operation | `PENDING_PHYSICAL` | Activate Emergency Stop while a real operation is in progress and prove it does not finish as success. |
