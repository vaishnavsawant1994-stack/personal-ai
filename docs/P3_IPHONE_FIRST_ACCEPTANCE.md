# P3 iPhone-First Phase A Acceptance Gates

A branch candidate may be called **Ready for Physical iPhone Testing** only when all of the following are true:

1. exact candidate SHA is recorded
2. normal repository CI is green on that SHA
3. `P3 iPhone PWA` security/integration workflow is green on that SHA
4. pull-request reliability/security checks required by the repository are green
5. no Home V1 or P2 capability files were changed except shared configuration required to expose the new settings
6. HTTPS enrollment fails closed when not configured or when the owner code is incorrect
7. device credentials are not exposed to JavaScript storage
8. protected PWA routes reject invalid/revoked devices
9. voice turns execute through the existing Personal AI executor with cooperative cancellation
10. P3.1 recorder receives transcript/reply/barge/cancel/state evidence
11. the candidate is not described as P3.1 passed, Reliable, Production or Superior

Physical iPhone qualification starts only after these implementation-readiness gates pass.
