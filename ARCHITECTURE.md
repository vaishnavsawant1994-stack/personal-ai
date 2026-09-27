# Personal AI Architecture V2

```text
Desktop UI / Local API
        |
     Event Bus
        |
   Agent Runtime
   /    |      \
Model  Memory  Tool Registry
Router  OS       |
                 Permission policy
                 |
        Files / Web / System / Docs / Screen / Reminders
```

## Current state machine

`idle -> listening -> thinking -> acting -> speaking -> idle`

## Safety design

- Remote server is loopback-only by default.
- Remote commands require a paired bearer token.
- Pairing offers are one-time and expire.
- Tool risk is enforced below the model.
- Side effects are blocked by default in `ask` mode.
- Tool execution is audited in SQLite.
- Plugins are manifest-based; arbitrary in-process Python import is intentionally excluded.
