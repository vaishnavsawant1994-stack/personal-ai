# P3 iPhone-First Phase A — Implementation State

Status: IMPLEMENTED / VALIDATION IN PROGRESS

Protected main baseline: `b28dca539081a963ff987ebd94153e065f17d78e`
Branch: `qualification/p3-iphone-first-20260908`
Specification baseline: `9843b15aad3c7613f2ad89b5e2495ad200f7801c`

## Implemented

- isolated iPhone PWA router mounted only in the cloud runtime
- HTTPS-only owner enrollment with constant-time enrollment-code verification
- trusted-device enrollment through the existing Personal AI device registry
- 30-day Secure + HttpOnly + SameSite=Strict device credential cookies
- revocation-aware authenticated PWA status and voice endpoints
- installable PWA shell, manifest and service worker
- Safari/WebKit speech-recognition microphone path with spoken browser replies
- state transitions for listening, understanding/thinking and speaking
- cooperative executor cancellation plus explicit local spoken-reply interruption
- P3.1 event emission (`voice.transcript`, `voice.reply`, `voice.barge_in`, `voice.turn.cancelled`, `state`)
- real-device qualification session start/stop/session-list integration with the existing P3.1 recorder
- captured evidence environment includes device id, `ios-pwa`, user agent and HTTPS-PWA transport
- tests for fail-closed HTTP enrollment, owner-code validation, secure cookie properties, trusted-device executor routing, and non-self-awarded qualification result

## Deliberate boundaries

- No Home V1 changes.
- No P2 capability rewrites.
- No `main` merge before exact-candidate validation.
- CI/browser/simulator evidence is implementation-readiness evidence only.
- P3.1 does not pass until physical iPhone trials satisfy the frozen voice gates.
- Browser speech API availability and real iPhone acoustic/barge-in performance must be verified on the physical device; those results are not fabricated by CI.

## Deployment requirements for physical testing

The cloud environment must provide:

- `PERSONAL_AI_IPHONE_ENROLLMENT_CODE` with a random value of at least 12 characters
- the selected Personal AI model/provider credentials on the server, never in browser JavaScript
- HTTPS termination
- persistent Personal AI data storage sufficient to retain trusted-device and P3 evidence databases

The physical test entry point is `/iphone/` on the deployed HTTPS Personal AI cloud runtime.
