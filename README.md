# Personal AI — Clean-Room Rebuild

Independent personal AI assistant codebase designed from scratch.

## Included in this V2 baseline

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

This project does not contain or reproduce Brahma Echo source code.
