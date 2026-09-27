# Personal AI iPhone Companion

The iOS companion is the primary real-device companion for the owner's current setup.

## Implemented foundation

- SwiftUI iPhone app foundation (iOS 17+)
- existing Personal AI desktop pairing token + six-digit code flow
- device identity and bearer credential stored in iOS Keychain with `ThisDeviceOnly` protection
- HTTPS/WSS required by default; plaintext HTTP/WS is an explicit development-only opt-in
- authenticated `URLSessionWebSocketTask` command channel
- reconnect on foreground/active lifecycle and scheduled `BGAppRefreshTask` refresh attempts
- device info and battery commands
- local notification delivery command
- URL/universal-link/custom-scheme handoff; arbitrary app launch is not claimed because iOS restricts it
- active `AVAudioSession` voice/microphone foundation using voice-chat mode
- simulator CI workflow
- separate physical-iPhone validation workflow

## iOS lifecycle boundary

iOS normally suspends ordinary apps in the background. The companion therefore does not pretend that a WebSocket is permanently alive after the app is backgrounded. It reconnects when the app becomes active and can receive system-scheduled background refresh opportunities. Continuous background execution is reserved for legitimate Apple-supported modes, such as an active audio session.

A later push-notification stage can add production APNs wake/notification delivery for server-initiated mobile events.

## Pairing

1. Start Personal AI on the trusted computer and create the one-time pairing offer locally.
2. On iPhone, enter the computer's secure HTTPS address, pairing token, and six-digit code.
3. Pairing returns a device ID and bearer credential. The bearer is written to Keychain and is never placed in a URL.

For development on a trusted LAN only, the UI has an explicit insecure HTTP/WS toggle. Production should use trusted HTTPS/WSS.

## Generate project

```bash
cd ios-companion
brew install xcodegen
xcodegen generate
open PersonalAICompanion.xcodeproj
```

For a real iPhone, configure signing with an Apple Development team in Xcode. The physical-device GitHub workflow expects a self-hosted macOS runner with the iPhone attached plus `IOS_DEVICE_UDID` and `IOS_DEVELOPMENT_TEAM` repository secrets.
