# P3.1 Physical iPhone Voice Qualification Protocol

Use only after the Phase A candidate is deployed behind HTTPS and implementation-readiness validation is green.

1. Open `/iphone/` on the physical iPhone.
2. Enroll the iPhone with the owner enrollment code.
3. Add the PWA to the Home Screen if desired.
4. Start a qualification session.
5. Grant microphone/speech-recognition permission when iOS asks.
6. Run natural voice conversations.
7. Across the campaign collect at least 30 real-device turns over at least 3 sessions.
8. Deliberately interrupt Personal AI at least 10 times while it is speaking.
9. Use at least three acoustic conditions/environments, such as quiet, normal room noise, and moderate background sound.
10. Stop each session and preserve its report.

Frozen P3.1 gates remain unchanged:

- >=30 real-device turns across >=3 sessions
- >=10 intentional barge-in trials
- barge-in success >=95%
- p95 interruption to Listening <=750 ms
- p95 transcript to reply <=5000 ms
- zero stale approvals/actions after interrupted turns
- zero unclassified voice errors

A PWA/CI/browser pass is not physical evidence. The P3.1 recorder and review process retain failures and do not lower gates to obtain a pass.
