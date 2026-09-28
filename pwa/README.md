# Personal AI iPhone PWA

This PWA is the responsive owner web/iPhone surface for the frozen Personal AI Home V1 and the physical-iPhone P3 qualification path.

The normal product experience is conversation-first:

- Home keeps the asymmetric living AI Core, persistent conversation, text input, document attachment and one-tap continuous voice.
- Mobile navigation exposes Home, Memory, Knowledge, Activities and More.
- The owner orb opens Settings, trusted devices and runtime/model status.
- Workflows, Apps & Tools, Devices and Dashboard remain behind progressive disclosure.
- P3 evidence controls live only in Settings > Advanced and never block normal conversation.

Production requirements:

- serve `server.cloud_app:app` behind HTTPS
- set `PERSONAL_AI_IPHONE_ENROLLMENT_CODE` to a random secret of at least 12 characters
- keep `PERSONAL_AI_IPHONE_ALLOW_INSECURE=false`
- configure the model/provider on the server; provider secrets never belong in browser storage
- use persistent storage for Personal AI data and P3 evidence

Open `/iphone/` on the physical iPhone. Enrollment creates a trusted `ios-pwa` device using the existing device registry and stores the resulting credential in Secure, HttpOnly, SameSite=Strict cookies.

A CI pass proves implementation readiness only. Physical voice qualification requires real iPhone sessions and the frozen P3.1 evidence gates.
