# Personal AI Architecture V4

V4 extends the validated V3 foundation with executable multimodal and device-facing capabilities.

```text
Desktop UI / Android Companion / Authenticated Local API
                   |
             Runtime & Events
     _____________|________________
    |             |                |
Realtime Voice  Agent Runtime   Control Dashboard
 STT->LLM->TTS      |                |
                    +---- Permission Engine
                    |
     Model Router --+-- Tool Registry -- Browser/Desktop
       |            |                  Automation
 chat/vision     Second Brain          Integrations
 embed/STT/TTS     |  |
                 Vector Graph
                    |
       Encrypted Secret Vault
                    |
       Signed Update Verifier
```

Security invariants: pairing initiation remains loopback-only; device API requires device id + bearer token; WebSocket tokens stay in headers; destructive/external tools remain governed by the V3 permission engine; dashboard tool execution cannot bypass confirmation policy; vault data uses AES-GCM with an scrypt-derived key; updates require Ed25519-signed manifests and SHA-256 package verification.
