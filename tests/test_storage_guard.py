from types import SimpleNamespace

import pytest

from core.storage import StorageUnavailable, validate_runtime_storage


def _settings(data_dir, *, hosted=False, cloud=False):
    return SimpleNamespace(
        data_dir=data_dir,
        hosted_runtime=hosted,
        cloud_runtime_enabled=cloud,
    )


def test_local_runtime_does_not_require_hosted_mount(tmp_path):
    data_dir = tmp_path / 'local-data'

    status = validate_runtime_storage(
        _settings(data_dir),
        environ={},
        mount_points=set(),
    )

    assert status['state'] == 'local'
    assert status['hosted'] is False
    assert status['durable'] is False
    assert status['data_dir'] == str(data_dir.resolve())
    assert data_dir.is_dir()


def test_hosted_runtime_rejects_data_dir_outside_durable_root(tmp_path):
    durable_root = tmp_path / 'volume'
    ephemeral = tmp_path / 'container-home' / '.personal_ai'

    with pytest.raises(StorageUnavailable, match='must resolve beneath'):
        validate_runtime_storage(
            _settings(ephemeral, hosted=True),
            environ={'PERSONAL_AI_DURABLE_ROOT': str(durable_root)},
            mount_points={durable_root},
        )


def test_hosted_runtime_rejects_unproven_mount(tmp_path):
    durable_root = tmp_path / 'volume'
    data_dir = durable_root / '.personal_ai'

    with pytest.raises(StorageUnavailable, match='cannot prove'):
        validate_runtime_storage(
            _settings(data_dir, hosted=True),
            environ={'PERSONAL_AI_DURABLE_ROOT': str(durable_root)},
            mount_points={tmp_path / 'some-other-mount'},
        )


def test_hosted_runtime_accepts_durable_mount_and_cleans_probe(tmp_path):
    durable_root = tmp_path / 'volume'
    data_dir = durable_root / '.personal_ai'
    durable_root.mkdir()

    status = validate_runtime_storage(
        _settings(data_dir, hosted=True),
        environ={'PERSONAL_AI_DURABLE_ROOT': str(durable_root)},
        mount_points={durable_root},
    )

    assert status == {
        'state': 'ready',
        'hosted': True,
        'data_dir': str(data_dir.resolve()),
        'durable_root': str(durable_root.resolve()),
        'durable': True,
        'mount_point': str(durable_root.resolve()),
    }
    assert list(data_dir.glob('.personal-ai-storage-probe-*')) == []


def test_cloud_runtime_also_requires_durable_mount(tmp_path):
    durable_root = tmp_path / 'volume'
    data_dir = durable_root / '.personal_ai'

    with pytest.raises(StorageUnavailable):
        validate_runtime_storage(
            _settings(data_dir, cloud=True),
            environ={'PERSONAL_AI_DURABLE_ROOT': str(durable_root)},
            mount_points=set(),
        )
