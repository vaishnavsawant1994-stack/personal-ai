import json

import pytest

from core.instance_identity import InstanceIdentityError, bind_instance_identity


def test_binds_fresh_persistent_directory_once(tmp_path):
    data_dir = tmp_path / "render-data"

    first = bind_instance_identity(data_dir, "render-independent")
    marker = data_dir / ".personal-ai-instance.json"
    original = marker.read_bytes()
    second = bind_instance_identity(data_dir, "render-independent")

    assert first["created"] == "true"
    assert second["created"] == "false"
    assert json.loads(original)["instance_id"] == "render-independent"
    assert marker.read_bytes() == original


def test_binds_existing_data_without_rewriting_it(tmp_path):
    data_dir = tmp_path / "railway-data"
    data_dir.mkdir()
    existing_db = data_dir / "assistant.sqlite3"
    existing_db.write_bytes(b"existing database bytes")

    bind_instance_identity(data_dir, "railway-primary")

    assert existing_db.read_bytes() == b"existing database bytes"
    assert json.loads((data_dir / ".personal-ai-instance.json").read_text())["instance_id"] == "railway-primary"


def test_refuses_identity_change_for_existing_installation(tmp_path):
    data_dir = tmp_path / "data"
    bind_instance_identity(data_dir, "railway-primary")
    marker = data_dir / ".personal-ai-instance.json"
    original = marker.read_bytes()

    with pytest.raises(InstanceIdentityError, match="different PERSONAL_AI_INSTANCE_ID"):
        bind_instance_identity(data_dir, "render-independent")

    assert marker.read_bytes() == original


def test_refuses_missing_or_invalid_identity(tmp_path):
    with pytest.raises(InstanceIdentityError, match="PERSONAL_AI_INSTANCE_ID is required"):
        bind_instance_identity(tmp_path / "data", "")
    with pytest.raises(InstanceIdentityError, match="PERSONAL_AI_INSTANCE_ID is required"):
        bind_instance_identity(tmp_path / "data", "Railway Primary")


def test_refuses_corrupt_marker_instead_of_replacing_it(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    marker = data_dir / ".personal-ai-instance.json"
    marker.write_text("not json", encoding="utf-8")

    with pytest.raises(InstanceIdentityError, match="marker is unreadable"):
        bind_instance_identity(data_dir, "railway-primary")

    assert marker.read_text(encoding="utf-8") == "not json"
