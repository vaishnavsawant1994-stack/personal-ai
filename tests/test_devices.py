from devices.registry import DeviceRegistry

def test_device_token_is_one_way_and_revocable(tmp_path):
    r=DeviceRegistry(tmp_path/"devices.sqlite3")
    d,token=r.enroll("Phone","android")
    assert r.authenticate(d["id"],token)
    assert r.revoke(d["id"])
    assert not r.authenticate(d["id"],token)
