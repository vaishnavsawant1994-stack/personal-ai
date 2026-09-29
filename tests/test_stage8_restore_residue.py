"""Stage-8: failed parent-symlink restore must not leave residue outside data root."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from recovery.backup import BackupError, BackupService
from test_v10_recovery import StaticRootKeyStore


def test_stage8_restore_parent_symlink_swap_leaves_no_external_residue(tmp_path, monkeypatch):
    if not hasattr(os, 'symlink'):
        pytest.skip('symlink unsupported')

    data = tmp_path / 'data'
    data.mkdir()
    nested = data / 'docs'
    nested.mkdir()
    (nested / 'note.txt').write_text('owner-state', encoding='utf-8')
    outside = tmp_path / 'outside'
    outside.mkdir()

    service = BackupService(data, root_key_store=StaticRootKeyStore(b'k' * 32))
    archive = service.create('residue-check.paibackup')

    target = tmp_path / 'restore-target'
    target.mkdir()
    (target / 'docs').mkdir()
    service.data_dir = target.resolve()
    service.backup_dir = target / 'backups'
    service.backup_dir.mkdir(exist_ok=True)

    real_safe = service._safe_destination
    swapped = {'done': False}

    def swap_then_safe(rel: Path):
        destination = real_safe(rel)
        parent = destination.parent
        if (
            not swapped['done']
            and parent != target
            and parent.exists()
            and parent.name == 'docs'
            and not parent.is_symlink()
        ):
            parent.rename(target / 'docs-real')
            try:
                parent.symlink_to(outside, target_is_directory=True)
            except OSError:
                pytest.skip('symlink creation not permitted')
            swapped['done'] = True
        return destination

    monkeypatch.setattr(service, '_safe_destination', swap_then_safe)

    before_outside = {p.name for p in outside.iterdir()} if outside.exists() else set()
    with pytest.raises(BackupError):
        service.restore(archive)
    after_outside = {p.name for p in outside.iterdir()} if outside.exists() else set()
    assert after_outside == before_outside
    assert swapped['done'] is True
