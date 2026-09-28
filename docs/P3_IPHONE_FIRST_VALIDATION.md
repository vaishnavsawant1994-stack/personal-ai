# P3 iPhone-First Validation Policy

Validation must be evaluated on one exact candidate SHA. A green workflow from an older branch head is not sufficient.

Required before physical iPhone testing:

- normal CI green on the exact candidate
- P3 iPhone PWA security/integration workflow green on the exact candidate
- pull-request reliability/security gates green on the exact candidate
- diff audit confirms Home V1 and P2 implementation remain frozen

Only after those gates pass may the candidate be deployed for real iPhone evidence. Deployment success itself is not a P3.1 pass.
