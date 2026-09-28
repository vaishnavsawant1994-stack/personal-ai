# Owner iPhone Flow

Once an exact Phase A candidate is validated and deployed behind HTTPS:

1. Open the Personal AI `/iphone/` URL on the owner's iPhone.
2. Enter the one-time owner enrollment code supplied out-of-band.
3. The server enrolls the iPhone as a trusted `ios-pwa` device.
4. The browser receives only Secure, HttpOnly, SameSite=Strict cookies; JavaScript never receives the bearer credential.
5. Start a P3.1 session.
6. Grant speech/microphone permission.
7. Speak normally; transcript text is sent to the existing Personal AI executor using the trusted device id.
8. Spoken replies use the browser speech engine.
9. Interrupt while Personal AI is speaking to record barge-in/cancel/listening evidence.
10. Stop the session and review the retained P3.1 result.

This flow does not require a laptop or Mac on the owner's side.
