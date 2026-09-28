import sqlite3

from devices.registry import DeviceRegistry

def test_device_token_is_one_way_and_revocable(tmp_path):
    r=DeviceRegistry(tmp_path/"devices.sqlite3")
    d,token=r.enroll("Phone","android")
    assert r.authenticate(d["id"],token)
    assert r.revoke(d["id"])
    assert not r.authenticate(d["id"],token)


def test_missing_permission_row_fails_closed_after_initial_migration(tmp_path):
    path = tmp_path / "devices.sqlite3"
    registry = DeviceRegistry(path)
    device, _ = registry.enroll("Desktop", "windows")
    assert registry.authorize(device["id"], "ai:chat")

    with sqlite3.connect(path) as con:
        con.execute("DELETE FROM device_permissions WHERE device_id=?", (device["id"],))

    assert registry.permissions(device["id"])["scopes"] == []
    assert registry.authorize(device["id"], "ai:chat") is False
