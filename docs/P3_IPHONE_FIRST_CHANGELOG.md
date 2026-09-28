# P3 iPhone-First Phase A Changelog

Candidate branch contents:

- `server/iphone_pwa.py` — secure enrollment, trusted-device auth, voice turn/barge endpoints, P3.1 evidence session endpoints
- `server/cloud_app.py` — mounts the isolated iPhone PWA router on the existing cloud runtime
- `pwa/index.html` — installable iPhone UI with speech input, spoken reply and interruption controls
- `pwa/manifest.webmanifest` / `pwa/sw.js` — PWA install/offline shell; API responses are not cached
- `core/config.py` / `.env.example` — fail-closed iPhone enrollment configuration
- `tests/test_p3_iphone_pwa.py` — enrollment/security/voice/qualification tests
- `.github/workflows/p3-iphone-pwa.yml` — dedicated security and integration gate
- P3 execution, protocol, security and acceptance documentation

No Home V1 UI file and no P2 capability implementation file is changed by this Phase A candidate.
