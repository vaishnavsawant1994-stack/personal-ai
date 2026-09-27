from types import SimpleNamespace
from fastapi.testclient import TestClient
from devices.registry import DeviceRegistry
from server.api import create_app

class Executor:
    def chat(self,text):return 'ok'

def test_authenticated_iphone_registers_apns_token(tmp_path):
    registry=DeviceRegistry(tmp_path/'devices.sqlite3');device,bearer=registry.enroll('Test iPhone','ios')
    settings=SimpleNamespace(pairing_ttl_seconds=300)
    app=create_app(Executor(),settings,device_registry=registry)
    client=TestClient(app)
    with client.websocket_connect(f"/device/ws/{device['id']}",headers={'Authorization':f'Bearer {bearer}'}) as ws:
        ws.send_json({'type':'push_registration','provider':'apns','token':'abcdef1234','environment':'development'})
        ack=ws.receive_json();assert ack['type']=='ack'
    meta=registry.metadata(device['id'])
    assert meta['push.apns.token']=='abcdef1234'
    assert meta['push.apns.environment']=='development'

def test_unauthorized_iphone_channel_is_rejected(tmp_path):
    registry=DeviceRegistry(tmp_path/'devices.sqlite3');device,_=registry.enroll('Test iPhone','ios')
    app=create_app(Executor(),SimpleNamespace(pairing_ttl_seconds=300),device_registry=registry)
    client=TestClient(app)
    try:
        with client.websocket_connect(f"/device/ws/{device['id']}",headers={'Authorization':'Bearer wrong'}):
            raise AssertionError('unauthorized websocket unexpectedly connected')
    except Exception:
        pass
