# Personal AI Companion beta privacy boundary

The iPhone companion is a device client for the owner's Personal AI system. It may request microphone, notification, background refresh, network, and device/battery access only for companion features implemented by the app.

Credentials issued during pairing are stored in iOS Keychain. Distribution credentials and APNs provider keys are never embedded in the repository or app source. TestFlight distribution credentials exist only in protected CI secrets and the ephemeral signing runner.

Physical-device telemetry/evidence must not contain Apple private keys, provisioning profiles, bearer credentials, pairing secrets, raw Keychain values, or unrelated personal content.
