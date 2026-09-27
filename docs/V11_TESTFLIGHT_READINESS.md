# V11 — TestFlight / real-iPhone distribution readiness

V11 prepares Personal AI Companion for secure cloud-built TestFlight distribution while preserving all physical evidence gates.

## Code-side completion

- Stable iOS bundle identifier and explicit release/build versions.
- GitHub-hosted macOS distribution validation using iOS 26+ SDK.
- Manual, fail-closed TestFlight upload job.
- Ephemeral signing keychain and provisioning-profile installation.
- App Store IPA export and signature verification.
- App Store Connect API-key upload path.
- Cleanup of temporary signing material.
- Protected `apple-distribution` environment boundary.
- Regression tests preventing silent removal of required security controls.

## Not evidence yet

The following remain false until actually executed:

- physical iPhone installation
- physical pairing
- authenticated command round-trip
- reconnect/interruption behavior
- revocation of an old credential
- live APNs delivery

No V11 code change may convert these evidence fields to true without real execution evidence.
