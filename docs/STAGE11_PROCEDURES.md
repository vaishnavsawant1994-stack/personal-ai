# Stage 11 procedures

These procedures stop at a real device or a real owner account. Do not fill a gap with CI, an emulator, or a simulator. A missing device stays `PENDING_PHYSICAL`. A missing owner login stays `PENDING_OWNER`.

Record every attempt with [STAGE11_EVIDENCE_FORMAT.md](STAGE11_EVIDENCE_FORMAT.md). A failed real attempt is `FAIL` or `BLOCKED`, then either a repair with a regression test or an explicit blocker. It is not a pass. Do not edit the register to `PASS` from this document.

The owner environment on record is one physical iPhone, no Apple Developer account, and no reported Android phone or laptop. Native iOS signing stays blocked. A Safari session counts only if it is captured against the exact source SHA. The old public `p2` site is not that SHA.

## S11-IOS-01 — iPhone trusted-device journey

**Preconditions.** A physical iPhone. The exact source SHA is the build under test, reached as a signed install or as the Safari PWA of that SHA. Owner can authenticate. A connector the consent matrix allows is available.

**Steps.**
1. Record the model, iOS version, and device identifier.
2. Authenticate as the owner and establish a trusted device.
3. Run a Conversation turn that reads Memory and Knowledge.
4. Run one connector action the consent matrix allows.
5. Revoke that device.
6. Repeat the same call.

**Expected result.** The journey works through the connector action. After revocation the same call fails.

**Evidence.** `real_device`, `form=physical`, source SHA, device id, operation id, and an audit reference for both the successful call and the failed call. Owner attestation is required.

**Failure handling.** No phone, no signing path, or no owner login: leave `PENDING_PHYSICAL+PENDING_OWNER`. A real call that still succeeds after revocation is `FAIL`. Do not substitute CI.

## S11-ANDROID-01 — Android trusted-device journey

**Preconditions.** A physical Android phone, confirmed not to be an emulator. The exact source SHA is installed. A second real surface exists for the handoff. Owner can authenticate.

**Steps.**
1. Authenticate, grant the permissions the journey uses, and keep the session.
2. Hand off continuity to the second surface or back.
3. Revoke the device.
4. Attempt to continue with the stale session.

**Expected result.** The session holds and the handoff is recorded. The stale session cannot continue after revocation.

**Evidence.** `real_device`, both device identifiers, the handoff operation id, and an audit reference showing the stale session rejected. Owner attestation is required.

**Failure handling.** No physical Android phone: leave `PENDING_PHYSICAL+PENDING_OWNER`. An emulator result is rejected and the row stays pending.

## S11-VOICE-01 — Physical microphone journey

**Preconditions.** A physical microphone on a real device. Permission can be granted. The exact source SHA is the runtime under test. Emergency Stop can be activated on that runtime.

**Steps.**
1. Grant microphone permission.
2. Capture speech, process it, call the model, and play a spoken response.
3. Interrupt or cancel a turn.
4. Activate Emergency Stop and attempt another capture.

**Expected result.** The granted capture produces a model response and speech. Cancel stops that turn. The capture after Emergency Stop does not run.

**Evidence.** `real_device`, device id, operation ids for the spoken turn, the cancelled turn, and the blocked capture, plus an audit reference. Not a fixture file and not a mocked stream.

**Failure handling.** No physical microphone: leave `PENDING_PHYSICAL`. Silence from the old `p2` site is not this case. A capture that continues after Emergency Stop is `FAIL`.

## S11-OAUTH-01 — Real provider login

**Preconditions.** The owner will complete a real provider login. No fixture token. The exact source SHA receives the callback.

**Steps.**
1. Sign in to the real provider.
2. Finish the callback and store the token.
3. Perform one permitted operation.
4. Revoke the provider.
5. Repeat the operation.

**Expected result.** The permitted operation succeeds once. After revocation the stored credential fails closed.

**Evidence.** `production_like` or `real_device` as appropriate, provider name, subject, operation id, and an audit reference for the success and the failure. Owner attestation is required.

**Failure handling.** Owner will not complete the login: leave `PENDING_OWNER`. Pasting a fixture token is not a result.

## S11-ESTOP-01 — Live Emergency Stop cycle

**Preconditions.** The deployed owner runtime for the exact source SHA. A real activity can be started. The explicit Emergency Stop reset path is available.

**Steps.**
1. Start a real activity.
2. Activate Emergency Stop.
3. Attempt a new execution.
4. Attempt a queued or retried execution.
5. Restart the server.
6. Reset only through the explicit authorization path and attempt execution again.

**Expected result.** New, queued, and retried work are blocked. After restart the stop is still on. After the explicit reset, execution works again.

**Evidence.** `real_device`, operation ids for the blocked attempts and the post-reset attempt, and an audit reference that includes the restart. Owner attestation is required when the owner server is restarted.

**Failure handling.** No live runtime: leave `PENDING_PHYSICAL`. A Stage 9 process restart test is not this case.

## S11-FAIL-01 — Network disappears during execution

**Preconditions.** A real operation is in progress on a physical device. The network path can be dropped without using a mock.

**Steps.**
1. Start the operation.
2. Drop the network before it finishes.
3. Restore the network.
4. Record whether anything is retried.

**Expected result.** The interrupted operation fails closed. Any retry after reconnect is recorded as itself, not as a silent success.

**Evidence.** `real_device`, operation id, timestamps for the drop and the reconnect, and an audit reference.

**Failure handling.** No physical network path: leave `PENDING_PHYSICAL`.

## S11-FAIL-02 — App backgrounded or killed

**Preconditions.** The exact source SHA is running on a physical handset. A real operation is in progress.

**Steps.**
1. Start the operation.
2. Background or kill the app before it finishes.
3. Reopen the app and record the recovered state.

**Expected result.** The recovered state is explicit. The operation does not become a silent success.

**Evidence.** `real_device`, device id, operation id, and an audit reference for the state after reopen.

**Failure handling.** No physical handset: leave `PENDING_PHYSICAL`.

## S11-FAIL-03 — Phone reconnects

**Preconditions.** A real phone had a dropped connection while using the exact source SHA.

**Steps.**
1. Reconnect the phone.
2. Attempt the same session.

**Expected result.** Record whether the session resumes or fails closed. Do not record both as success.

**Evidence.** `real_device`, device id, session or operation id, and an audit reference.

**Failure handling.** No physical handset: leave `PENDING_PHYSICAL`.

## S11-FAIL-04 — Stale session reused

**Preconditions.** A real device session exists and can be made stale by revocation, expiry, or logout on that device.

**Steps.**
1. Capture the session credential after it is stale.
2. Replay it against the exact source SHA.

**Expected result.** The replay is rejected.

**Evidence.** `real_device`, device id, operation id, and an audit reference for the rejection.

**Failure handling.** No physical session to make stale: leave `PENDING_PHYSICAL`.

## S11-FAIL-05 — Device revoked while active

**Preconditions.** A physical handset has an active authenticated session on the exact source SHA.

**Steps.**
1. Start a call from that session.
2. Revoke the device while the session is still active.
3. Make a later call with the same session.

**Expected result.** The later call fails.

**Evidence.** `real_device`, device id, both operation ids, and an audit reference.

**Failure handling.** No physical handset: leave `PENDING_PHYSICAL`.

## S11-FAIL-06 — Provider credential revoked externally

**Preconditions.** A real provider credential was stored by `S11-OAUTH-01` or an equivalent owner login on the exact source SHA. The owner can revoke it at the provider, outside Personal AI.

**Steps.**
1. Revoke the credential at the provider.
2. Attempt the next permitted call from Personal AI.

**Expected result.** That call fails closed.

**Evidence.** Provider name, subject, operation id, and an audit reference. Owner attestation is required.

**Failure handling.** Owner will not use the provider: leave `PENDING_OWNER`.

## S11-FAIL-07 — Microphone permission denied or revoked

**Preconditions.** A real device with a physical microphone. Permission can be denied or revoked in the system settings.

**Steps.**
1. Deny the permission, or revoke it after a previous grant.
2. Attempt a capture on the exact source SHA.

**Expected result.** Capture does not proceed.

**Evidence.** `real_device`, device id, operation id, and an audit reference showing the permission state.

**Failure handling.** No physical microphone: leave `PENDING_PHYSICAL`.

## S11-FAIL-08 — Server restarted while stopped

**Preconditions.** The owner server for the exact source SHA is running and Emergency Stop is on.

**Steps.**
1. Confirm Emergency Stop is on.
2. Restart that server.
3. Read the stop state and attempt a new execution.

**Expected result.** The stop is still on. The new execution does not run.

**Evidence.** `real_device` or `production_like` for the owner server, operation id, and an audit reference from after the restart. Owner attestation is required.

**Failure handling.** No owner server to restart: leave `PENDING_PHYSICAL+PENDING_OWNER`. A Stage 9 restart test is not this case.

## S11-FAIL-09 — Two-device handoff

**Preconditions.** Two real devices. The exact source SHA is what both use. One device can be revoked.

**Steps.**
1. Start a session on the first device.
2. Hand off to the second device.
3. Revoke one device.
4. Attempt to continue from the revoked device and from the surviving device.

**Expected result.** Record which session survives. The revoked device does not continue.

**Evidence.** Both device ids, the handoff operation id, and an audit reference. Owner attestation is required.

**Failure handling.** Fewer than two real devices: leave `PENDING_PHYSICAL+PENDING_OWNER`.

## S11-FAIL-10 — Emergency Stop during an operation

**Preconditions.** A real operation is in progress on the exact source SHA. Emergency Stop can be activated before it finishes.

**Steps.**
1. Start the operation.
2. Activate Emergency Stop before it completes.
3. Record the final state of that operation.

**Expected result.** The operation does not finish as success.

**Evidence.** `real_device`, operation id, and an audit reference for the stop and the operation outcome.

**Failure handling.** No physical operation to interrupt: leave `PENDING_PHYSICAL`.
