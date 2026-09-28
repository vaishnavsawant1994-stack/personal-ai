# Personal AI for Android

The Android application provides two owner-controlled surfaces:

- **Open Personal AI** launches the production cloud experience in a secure Chrome
  Custom Tab. This preserves Google sign-in, trusted-device cookies, microphone
  access, voice responses and conversation continuity.
- **Advanced device pairing** retains the encrypted local-computer companion and
  background command channel. Pairing credentials stay in Android encrypted
  preferences.

CI builds an installable debug APK and publishes it with a SHA-256 checksum. The
debug artifact is suitable for owner testing and must be replaced by a privately
held release signing key before public distribution or Play Store publishing.
