# Personal AI

Independent personal AI assistant codebase designed from scratch.

## Current integrated product

- PyQt6 desktop shell
- Living pulse AI visual states
- Model router (Local OpenAI-compatible + OpenRouter)
- SQLite conversations, memory objects, relationships, tasks and audit events
- Memory graph data service
- Tool registry with risk levels
- Autonomy modes: observe / suggest / ask / act
- Agent planner + executor with structured step results
- File tools
- Browser opener/search URL tools
- System information + safe app launcher
- Notes and reminders
- Document helpers for DOCX/PPTX/XLSX
- Screen screenshot capture hook
- Voice input/output service interfaces
- Local FastAPI control API
- Device pairing foundation with authenticated bearer tokens
- Plugin manifest model (no arbitrary in-process import)
- Event/audit bus
- Configuration and secrets abstraction
- Tests
- GitHub Actions CI file
- Packaging entrypoints
- iPhone/PWA persistent conversations and hands-free voice
- Owner-facing Memory Graph, Tree, Detail and controls
- Separate document Knowledge ingestion, search and citations
- Durable governed workflows, recovery and emergency stop
- Per-device scopes, device listing and revocation
- Replaceable cloud/self-hosted model routing

Operational details: [`docs/OWNER_PRODUCT_OPERATIONS.md`](docs/OWNER_PRODUCT_OPERATIONS.md).

## Run

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # Windows
# or: cp .env.example .env
python -m app.main
```

## Secure vault startup

Personal AI fails closed when it cannot unlock its encrypted secret vault. The
recommended desktop configuration stores the generated root key in the operating
system keychain. On a headless machine or in CI, set
`PERSONAL_AI_VAULT_PASSWORD` to a strong value supplied by the deployment secret
store. Never commit that password, an exported root key, provider tokens, or
signing material to this repository.

For a local non-interactive smoke test:

```bash
PERSONAL_AI_VAULT_PASSWORD='temporary-test-only' python -m app.main
```

The example value is for disposable test data only. Production deployments must
use an owner-controlled secret and a durable data directory. Optional provider,
signing, device and microphone features may remain unconfigured; their absence
must be reported as deferred external qualification rather than bypassed.

This project does not contain or reproduce Brahma Echo source code.
