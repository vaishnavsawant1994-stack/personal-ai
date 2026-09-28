# P3 — iPhone-First Real-Device Qualification

Status: EXECUTION BRANCH
Base: `b28dca539081a963ff987ebd94153e065f17d78e`
Branch: `qualification/p3-iphone-first-20260908`

## Purpose

The owner currently has an iPhone but no Windows or macOS computer. P3 must therefore collect genuine physical-device evidence from the iPhone where possible without fabricating Windows evidence or weakening any frozen P3 gate.

Home V1 and P2 remain frozen. Existing P3 qualification infrastructure remains authoritative.

## Verified current state

The native iOS companion already provides SwiftUI, Keychain-protected device credentials, secure HTTPS/WSS transport by default, authenticated device WebSocket connectivity, reconnect behavior, APNs registration foundations, background refresh, and AVAudioSession microphone/voice-chat activation.

However, the native companion currently assumes a Personal AI computer/server is already running and requires a computer-created pairing token/code. Its voice implementation currently activates the audio session and microphone permission but does not implement a complete iPhone conversational voice transport into the Personal AI runtime.

TestFlight automation exists, but real TestFlight distribution requires Apple Developer Program/App Store Connect signing material. No signing secret may be committed to the repository.

## Frozen execution direction

### Phase A — iPhone-first cloud/PWA qualification client

Build a secure owner-facing PWA that runs from Safari/Home Screen and talks to the existing Personal AI cloud runtime.

Required capabilities:

1. Secure owner enrollment without requiring a desktop pairing ceremony.
2. Session/device identity suitable for real-device evidence attribution.
3. iPhone microphone capture using browser-supported media APIs.
4. Full conversational voice request/response path to the existing Personal AI runtime.
5. Explicit start/stop and interruption controls for P3.1 trials.
6. Qualification event timestamps sufficient for latency and barge-in evidence.
7. Evidence submission/export into the existing P3 qualification ledger without letting the client self-award qualification states.
8. Installable PWA metadata and iPhone-safe lifecycle behavior.
9. No API/provider secrets embedded in browser code.
10. Fail-closed authentication, origin and transport policy.

### Phase B — native iPhone companion

After Phase A yields usable physical evidence, extend the existing native companion for TestFlight and deeper P3.6 continuity evidence:

- native conversational voice transport
- APNs-backed server-initiated notifications
- reconnect/handoff evidence
- revocation and stale-credential rejection
- device attribution
- physical continuity trials

## Qualification integrity

- PWA or native simulator runs are not physical-device evidence.
- Safari on the owner's physical iPhone may count as real-device evidence only when the qualification recorder receives device/environment metadata and the required measurements from an authenticated physical session.
- Windows-specific P3.2 evidence remains deferred until a genuine Windows environment exists.
- No P3 gate may be lowered because the owner currently lacks a Windows/Mac computer.
- Structural/simulated evidence cannot promote Reliable, Production or Superior.
- Competitive P3.8 remains blocked by its frozen prerequisites.

## Immediate implementation sequence

1. Reuse `server/cloud_app.py` and the existing Personal AI runtime/API rather than creating a second backend.
2. Add owner-enrollment/session endpoints with short-lived bootstrap credentials and revocation.
3. Add authenticated mobile/PWA conversation transport.
4. Add browser microphone capture and conversational voice state machine.
5. Emit/ingest P3.1 evidence timestamps and interruption outcomes.
6. Add installable PWA shell and secure deployment configuration.
7. Add unit/integration/browser tests.
8. Validate exact branch SHA through CI/security/mobile checks.
9. Only then deploy a qualification build for physical iPhone trials.

## User-side requirements for Phase A

None during repository implementation. The owner must not send API keys, Apple credentials, passwords, certificates or signing material.

When the PWA qualification build is ready, the owner will only need to open the HTTPS URL on the physical iPhone, enroll the device, grant microphone permission, add the PWA to the Home Screen if desired, run the instructed real voice sessions, deliberately perform interruption trials, and allow the system to upload/export the resulting evidence.
