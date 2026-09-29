"""Inventory of owner SQLite stores and how each one can be recovered.

This is not a migration runner and it does not open Stage 12.
There is no schema rollback.
"""

from __future__ import annotations

from recovery.backup import NON_RESTORABLE_SECURITY_NAMES


# Basename match. A file with one of these names is archived and then skipped
# on restore, including when it lives in a subdirectory.
UNRESTORABLE = frozenset(NON_RESTORABLE_SECURITY_NAMES)

# Every production *.sqlite3 filename. schema is always forward-fix.
# transaction is always the current connection, not a cross-database rollback.
STORES: dict[str, str] = {
    'assistant.sqlite3': 'backup',
    'automations.sqlite3': 'backup',
    'autonomy.sqlite3': 'backup',
    'capability-benchmark.sqlite3': 'backup',
    'cloud-sessions.sqlite3': 'unrestorable_security_state',
    'connectors.sqlite3': 'unrestorable_security_state',
    'continuity.sqlite3': 'backup',
    'devices.sqlite3': 'unrestorable_security_state',
    'everyday.sqlite3': 'backup',
    'knowledge.sqlite3': 'backup',
    'life-graph.sqlite3': 'backup',
    'memory-candidates.sqlite3': 'backup',
    'model-dialogue-evaluation.sqlite3': 'backup',
    'operations.sqlite3': 'backup',
    'operator-policies.sqlite3': 'unrestorable_security_state',
    'operator-transactions.sqlite3': 'unrestorable_security_state',
    'owner-access.sqlite3': 'unrestorable_security_state',
    'p3-qualification.sqlite3': 'backup',
    'proactive.sqlite3': 'backup',
    'pwa-sessions.sqlite3': 'unrestorable_security_state',
    'runtime-controls.sqlite3': 'unrestorable_security_state',
    'trusted-action-audit.sqlite3': 'backup',
    'trusted-actions.sqlite3': 'unrestorable_security_state',
    'turn-runtime.sqlite3': 'backup',
    'vectors.sqlite3': 'backup',
    'voice-qualification.sqlite3': 'backup',
    'workflow-budgets.sqlite3': 'backup',
    'world.sqlite3': 'backup',
}


def restore_class(filename: str) -> str:
    try:
        return STORES[filename]
    except KeyError as exc:
        raise KeyError(f'unclassified database: {filename}') from exc
