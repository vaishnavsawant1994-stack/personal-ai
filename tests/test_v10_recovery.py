from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest

from recovery.backup import BACKUP_MAGIC, BackupError, BackupService


class StaticRootKeyStore:
    def __init__(self, key: bytes):
        self.key = key

    def get_or_create(self):
        return self.key


def service(data: Path, key: bytes = b'k' * 32):
    return BackupService(data, root_key_store=StaticRootKeyStore(key))


def test_backup_is_encrypted_excludes_secret_store_and_restores(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'note.txt').write_text('hello')
    (data / 'vault.json').write_text('secret')
    (data / '.env').write_text('TOKEN=x')
    db = data / 'assistant.sqlite3'
    with sqlite3.connect(db) as con:
        con.execute('create table t(v text)')
        con.execute('insert into t values(?)', ('before',))

    svc = service(data)
    archive = svc.create('test.paibackup')

    assert archive.read_bytes().startswith(BACKUP_MAGIC)
    assert not zipfile.is_zipfile(archive)
    manifest = svc.inspect(archive)
    paths = {item['path'] for item in manifest['files']}
    assert manifest['version'] == 2
    assert manifest['encrypted'] is True
    assert manifest['cipher'] == 'AES-256-GCM'
    assert 'note.txt' in paths and 'assistant.sqlite3' in paths
    assert 'vault.json' not in paths and '.env' not in paths

    (data / 'note.txt').write_text('changed')
    result = svc.restore(archive)
    assert result['ok'] is True and result['encrypted'] is True
    assert (data / 'note.txt').read_text() == 'hello'
    assert (data / 'vault.json').read_text() == 'secret'
    with sqlite3.connect(db) as con:
        assert con.execute('select v from t').fetchone()[0] == 'before'


def test_backup_wrong_root_key_fails_closed(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'a.txt').write_text('A')
    archive = service(data, b'a' * 32).create('x.paibackup')

    with pytest.raises(BackupError, match='authentication failed'):
        service(data, b'b' * 32).inspect(archive)


def test_backup_detects_encrypted_archive_tampering(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'a.txt').write_text('A' * 4096)
    archive = service(data).create('x.paibackup')
    corrupt = tmp_path / 'bad.paibackup'
    raw = bytearray(archive.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    corrupt.write_bytes(raw)

    with pytest.raises(BackupError):
        service(data).inspect(corrupt)


def test_live_wal_database_is_snapshotted_without_sidecars(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    db = data / 'assistant.sqlite3'
    con = sqlite3.connect(db)
    try:
        con.execute('pragma journal_mode=WAL')
        con.execute('create table state(v text)')
        con.execute('insert into state values(?)', ('at-backup',))
        con.commit()
        archive = service(data).create('wal.paibackup')
        manifest = service(data).inspect(archive)
        paths = {item['path'] for item in manifest['files']}
        assert 'assistant.sqlite3' in paths
        assert not any(path.endswith(('-wal', '-shm', '-journal')) for path in paths)

        con.execute('update state set v=?', ('after-backup',))
        con.commit()

        restored = tmp_path / 'restored'
        restored.mkdir()
        service(restored).restore(archive)
        with sqlite3.connect(restored / 'assistant.sqlite3') as restored_db:
            assert restored_db.execute('select v from state').fetchone()[0] == 'at-backup'
    finally:
        con.close()


def test_restore_validates_all_databases_before_overwriting_owner_files(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'note.txt').write_text('original')

    note = b'restored note'
    broken_db = b'this is not a sqlite database'
    manifest = {
        'version': 1,
        'created_at': 1.0,
        'files': [
            {'path': 'note.txt', 'size': len(note), 'sha256': hashlib.sha256(note).hexdigest()},
            {
                'path': 'broken.sqlite3',
                'size': len(broken_db),
                'sha256': hashlib.sha256(broken_db).hexdigest(),
            },
        ],
    }
    archive = tmp_path / 'legacy-broken.paibackup'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('note.txt', note)
        zipped.writestr('broken.sqlite3', broken_db)
        zipped.writestr('manifest.json', json.dumps(manifest))

    with pytest.raises(BackupError, match='database integrity failure'):
        service(data).restore(archive)
    assert (data / 'note.txt').read_text() == 'original'
    assert not (data / 'broken.sqlite3').exists()


def test_restore_rolls_back_all_replaced_files_when_late_replace_fails(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a.txt').write_text('backup-a')
    (source / 'b.txt').write_text('backup-b')
    archive = service(source).create('rollback.paibackup')

    target = tmp_path / 'target'
    target.mkdir()
    (target / 'a.txt').write_text('owner-a')
    (target / 'b.txt').write_text('owner-b')

    import recovery.backup as backup_module

    real_replace = backup_module.os.replace
    restore_replaces = 0

    def injected_replace(src, dst):
        nonlocal restore_replaces
        if str(src).endswith('.restore'):
            restore_replaces += 1
            if restore_replaces == 2:
                raise OSError('simulated disk failure')
        return real_replace(src, dst)

    monkeypatch.setattr(backup_module.os, 'replace', injected_replace)
    with pytest.raises(BackupError, match='rolled back'):
        service(target).restore(archive)

    assert (target / 'a.txt').read_text() == 'owner-a'
    assert (target / 'b.txt').read_text() == 'owner-b'


def test_restore_refuses_existing_symlink_destination(tmp_path):
    if not hasattr(os, 'symlink'):
        pytest.skip('symlink unsupported')

    source = tmp_path / 'source'
    source.mkdir()
    nested = source / 'nested'
    nested.mkdir()
    (nested / 'note.txt').write_text('safe backup')
    archive = service(source).create('symlink.paibackup')

    target = tmp_path / 'target'
    target.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (target / 'nested').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation not permitted')

    with pytest.raises(BackupError, match='unsafe restore destination'):
        service(target).restore(archive)
    assert not (outside / 'note.txt').exists()


def test_backup_skips_symlinked_source_files(tmp_path):
    if not hasattr(os, 'symlink'):
        pytest.skip('symlink unsupported')
    data = tmp_path / 'data'
    data.mkdir()
    outside = tmp_path / 'outside.txt'
    outside.write_text('must not be backed up')
    link = data / 'linked.txt'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation not permitted')
    (data / 'normal.txt').write_text('included')

    manifest = service(data).inspect(service(data).create('symlink-source.paibackup'))
    paths = {item['path'] for item in manifest['files']}
    assert 'normal.txt' in paths
    assert 'linked.txt' not in paths


def test_legacy_backup_detects_payload_tampering(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    archive = tmp_path / 'legacy.paibackup'
    original = b'A'
    manifest = {
        'version': 1,
        'created_at': 1.0,
        'files': [
            {'path': 'a.txt', 'size': len(original), 'sha256': hashlib.sha256(original).hexdigest()}
        ],
    }
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('a.txt', b'B')
        zipped.writestr('manifest.json', json.dumps(manifest))

    with pytest.raises(BackupError, match='integrity failure'):
        service(data).inspect(archive)


def test_backup_rejects_traversal(tmp_path):
    archive = tmp_path / 'bad.paibackup'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('../escape.txt', 'x')
        zipped.writestr('manifest.json', json.dumps({'version': 1, 'files': []}))
    with pytest.raises(BackupError, match='unsafe backup path'):
        service(tmp_path / 'data').inspect(archive)


def _write_security_db(path: Path, value: str):
    with sqlite3.connect(path) as con:
        con.execute('create table if not exists state(v text)')
        con.execute('delete from state')
        con.execute('insert into state values(?)', (value,))


def _read_security_db(path: Path) -> str:
    with sqlite3.connect(path) as con:
        return con.execute('select v from state').fetchone()[0]


def test_stage8_restore_does_not_resurrect_security_state(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    _write_security_db(source / 'devices.sqlite3', 'trusted-before-revocation')
    _write_security_db(source / 'pwa-sessions.sqlite3', 'active-before-revocation')
    _write_security_db(source / 'trusted-actions.sqlite3', 'security-epoch-1')
    (source / 'note.txt').write_text('backup-note')
    archive = service(source).create('security-state.paibackup')

    target = tmp_path / 'target'
    target.mkdir()
    _write_security_db(target / 'devices.sqlite3', 'revoked-current')
    _write_security_db(target / 'pwa-sessions.sqlite3', 'revoked-session-current')
    _write_security_db(target / 'trusted-actions.sqlite3', 'security-epoch-9')
    (target / 'note.txt').write_text('changed-note')

    result = service(target).restore(archive)

    assert result['ok'] is True
    assert (target / 'note.txt').read_text() == 'backup-note'
    assert _read_security_db(target / 'devices.sqlite3') == 'revoked-current'
    assert _read_security_db(target / 'pwa-sessions.sqlite3') == 'revoked-session-current'
    assert _read_security_db(target / 'trusted-actions.sqlite3') == 'security-epoch-9'
    assert set(result['skipped_security_state']) >= {
        'devices.sqlite3', 'pwa-sessions.sqlite3', 'trusted-actions.sqlite3',
    }


def test_stage8_restore_to_empty_target_does_not_create_archived_security_authority(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    _write_security_db(source / 'devices.sqlite3', 'trusted-old')
    _write_security_db(source / 'owner-access.sqlite3', 'old-owner-auth')
    (source / 'memory.txt').write_text('recoverable owner data')
    archive = service(source).create('empty-target.paibackup')

    target = tmp_path / 'target'
    target.mkdir()
    result = service(target).restore(archive)

    assert (target / 'memory.txt').read_text() == 'recoverable owner data'
    assert not (target / 'devices.sqlite3').exists()
    assert not (target / 'owner-access.sqlite3').exists()
    assert set(result['skipped_security_state']) >= {'devices.sqlite3', 'owner-access.sqlite3'}
