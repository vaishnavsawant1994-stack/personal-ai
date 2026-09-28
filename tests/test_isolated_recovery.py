from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from recovery.backup import BACKUP_MAGIC, BackupService


class FixedKeyStore:
    def get_or_create(self):
        return b'R' * 32


def _db(path: Path, table: str, values: list[tuple[str, str]]):
    with sqlite3.connect(path) as con:
        con.execute(f'create table {table}(id text primary key, value text not null)')
        con.executemany(f'insert into {table}(id,value) values(?,?)', values)


def _rows(path: Path, table: str):
    with sqlite3.connect(path) as con:
        assert con.execute('pragma integrity_check').fetchone()[0] == 'ok'
        return con.execute(f'select id,value from {table} order by id').fetchall()


def _sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_isolated_operational_backup_restore_reopens_all_state(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir()
    target.mkdir()

    _db(source / 'assistant.sqlite3', 'memory_rows', [('m1', 'preference'), ('m2', 'commitment')])
    _db(source / 'continuity.sqlite3', 'message_rows', [('c1', 'hello'), ('c2', 'continue')])
    _db(source / 'trusted-actions.sqlite3', 'approval_rows', [('a1', 'checkpoint')])
    (source / 'preferences.json').write_text('{"voice":true}', encoding='utf-8')

    backup = BackupService(source, root_key_store=FixedKeyStore())
    archive = backup.create('isolated.paibackup')
    assert archive.read_bytes().startswith(BACKUP_MAGIC)
    manifest = backup.inspect(archive)
    expected = {row['path']: row['sha256'] for row in manifest['files']}

    (target / 'assistant.sqlite3').write_bytes(b'invalid old state')
    (target / 'unrelated.txt').write_text('preserve', encoding='utf-8')
    result = BackupService(target, root_key_store=FixedKeyStore()).restore(archive)

    assert result['ok'] is True
    assert result['encrypted'] is True
    assert _rows(target / 'assistant.sqlite3', 'memory_rows') == [('m1', 'preference'), ('m2', 'commitment')]
    assert _rows(target / 'continuity.sqlite3', 'message_rows') == [('c1', 'hello'), ('c2', 'continue')]
    assert 'trusted-actions.sqlite3' in result['skipped_security_state']
    assert not (target / 'trusted-actions.sqlite3').exists()
    assert (target / 'preferences.json').read_text(encoding='utf-8') == '{"voice":true}'
    assert (target / 'unrelated.txt').read_text(encoding='utf-8') == 'preserve'
    for rel, digest in expected.items():
        if rel in set(result['skipped_security_state']):
            continue
        assert _sha(target / rel) == digest
