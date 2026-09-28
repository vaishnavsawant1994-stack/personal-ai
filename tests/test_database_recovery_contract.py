"""The recovery contract matches the stores and the restore behavior."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from recovery.backup import EXCLUDED_NAMES, NON_RESTORABLE_SECURITY_NAMES, BackupService
from recovery.database_contract import STORES, UNRESTORABLE


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'docs' / 'DATABASE_RECOVERY_CONTRACT.md'
NAME = re.compile(r"""['\"]([A-Za-z0-9_.-]+\.sqlite3)['\"]""")


class StaticRootKeyStore:
    def get_or_create(self):
        return b'k' * 32


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute('create table if not exists state(v text)')
        con.execute('delete from state')
        con.execute('insert into state values(?)', (value,))


def _read(path: Path) -> str:
    with sqlite3.connect(path) as con:
        return con.execute('select v from state').fetchone()[0]


def test_contract_classes_match_the_code_and_the_note():
    note = CONTRACT.read_text(encoding='utf-8')
    assert 'not a stage freeze' in note
    assert 'Stage 12 is not open' in note
    assert 'no unified database rollback' in note
    assert 'schema rollback' in note.lower()
    assert set(STORES) == set(NAME.findall('\n'.join(
        path.read_text(encoding='utf-8')
        for path in ROOT.rglob('*.py')
        if 'tests' not in path.parts and '.git' not in path.parts and path.is_file()
    )))
    assert UNRESTORABLE == frozenset(NON_RESTORABLE_SECURITY_NAMES)
    assert {name for name, kind in STORES.items() if kind == 'unrestorable_security_state'} == UNRESTORABLE
    assert not any(kind == 'schema_rollback' for kind in STORES.values())
    for name in STORES:
        assert name in note
    for secret in EXCLUDED_NAMES:
        assert secret in note


def test_restore_cannot_resurrect_any_security_store(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for name in sorted(UNRESTORABLE):
        _write(source / 'nested' / name, 'archived-authority')
    _write(source / 'assistant.sqlite3', 'archived-memory')
    archive = BackupService(source, root_key_store=StaticRootKeyStore()).create('recovery.paibackup')

    target = tmp_path / 'target'
    target.mkdir()
    for name in sorted(UNRESTORABLE):
        _write(target / 'nested' / name, 'current-authority')
    _write(target / 'assistant.sqlite3', 'current-memory')
    result = BackupService(target, root_key_store=StaticRootKeyStore()).restore(archive)

    assert result['ok'] is True
    assert _read(target / 'assistant.sqlite3') == 'archived-memory'
    assert {Path(item).name for item in result['skipped_security_state']} == set(UNRESTORABLE)
    for name in UNRESTORABLE:
        assert _read(target / 'nested' / name) == 'current-authority'

    empty = tmp_path / 'empty'
    empty.mkdir()
    BackupService(empty, root_key_store=StaticRootKeyStore()).restore(archive)
    for name in UNRESTORABLE:
        assert not (empty / 'nested' / name).exists()
    assert _read(empty / 'assistant.sqlite3') == 'archived-memory'
