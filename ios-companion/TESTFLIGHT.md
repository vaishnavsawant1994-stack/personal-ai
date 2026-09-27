# Personal AI iPhone — TestFlight distribution

This project is prepared for real-iPhone beta distribution through Apple TestFlight without requiring the owner to keep a Mac.

## What is automated

`.github/workflows/ios-testflight.yml` performs two separate stages:

1. **Validate** — runs on a GitHub-hosted macOS runner, verifies an iOS 26+ SDK, generates the Xcode project, and creates an unsigned Release archive as a distribution-readiness smoke test.
2. **Upload TestFlight** — runs only when manually requested with `upload=true`. It fails closed unless all Apple signing/App Store Connect credentials are present, installs them only in the ephemeral runner, creates a signed App Store archive/IPA, verifies the signature, uploads the IPA to App Store Connect, then removes temporary signing material.

No certificate, private key, provisioning profile, Apple password, or API token belongs in this public repository.

## Apple account prerequisites

Before a real TestFlight upload can succeed, the owner must have:

- Active Apple Developer Program membership.
- App Store Connect app record for **Personal AI Companion**.
- Bundle ID exactly `ai.personal.companion.ios` registered to the Apple developer team.
- App Store distribution certificate and matching private key exported as `.p12`.
- App Store provisioning profile for `ai.personal.companion.ios` with required capabilities, including push notifications.
- App Store Connect API key with sufficient access to upload builds.

## GitHub environment

Create a protected GitHub environment named `apple-distribution`. Store the following as encrypted secrets there (never commit them):

- `APPLE_TEAM_ID`
- `APP_STORE_CONNECT_KEY_ID`
- `APP_STORE_CONNECT_ISSUER_ID`
- `APP_STORE_CONNECT_PRIVATE_KEY_B64` — base64 of the `.p8` App Store Connect API private key
- `IOS_DISTRIBUTION_CERT_P12_B64` — base64 of the distribution `.p12`
- `IOS_DISTRIBUTION_CERT_PASSWORD`
- `IOS_APPSTORE_PROFILE_B64` — base64 of the App Store provisioning profile

The existing APNs server credentials remain separate from distribution credentials.

## First physical-iPhone path

1. Complete Apple Developer membership and create the app/bundle identifier in App Store Connect.
2. Add the protected GitHub environment secrets above.
3. Manually run **iOS TestFlight Distribution** with `upload=true`.
4. Wait for Apple to process the uploaded build.
5. Add the owner as an internal tester where possible; otherwise configure an external TestFlight group and complete any required Beta App Review.
6. On the iPhone, install Apple's TestFlight app and accept the invitation.
7. Install Personal AI Companion.
8. Execute the physical evidence sequence: pairing → authenticated WebSocket → command round-trip → reconnect → device revocation → verify old credential rejected → APNs delivery.

## Fail-closed rule

A successful simulator build or unsigned archive does **not** count as physical-iPhone evidence. A TestFlight upload does **not** count as successful physical operation. Production readiness remains false until the physical evidence fields in `readiness/evidence-template.json` are actually satisfied.
