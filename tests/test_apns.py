from types import SimpleNamespace
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from notifications.apns import APNsProvider
from devices.registry import DeviceRegistry

class Response:
    def __init__(self,status=200,reason='',headers=None):self.status_code=status;self._reason=reason;self.headers=headers or {};self.content=b'{}' if reason else b'';self.text=''
    def json(self):return {'reason':self._reason}
class Client:
    def __init__(self,response):self.response=response;self.calls=[]
    def post(self,url,headers=None,json=None):self.calls.append((url,headers,json));return self.response
    def close(self):pass

def settings():
    key=ec.generate_private_key(ec.SECP256R1());pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    return SimpleNamespace(apns_team_id='TEAM123456',apns_key_id='KEY1234567',apns_topic='ai.personal.companion.ios',apns_private_key_b64=base64.b64encode(pem).decode(),apns_environment='development')

def test_provider_token_is_cached_and_es256_shaped():
    p=APNsProvider(settings(),client=Client(Response()))
    a=p.provider_token(now=1000);b=p.provider_token(now=1100)
    assert a==b and len(a.split('.'))==3
    raw=base64.urlsafe_b64decode(a.split('.')[2]+'==');assert len(raw)==64

def test_apns_success_uses_http2_provider_contract():
    c=Client(Response(200,headers={'apns-id':'abc'}));p=APNsProvider(settings(),client=c)
    r=p.send_token('deadbeef','Personal AI','Ready',data={'kind':'test'})
    assert r.ok and r.apns_id=='abc'
    url,headers,payload=c.calls[0]
    assert url.endswith('/3/device/deadbeef')
    assert headers['apns-topic']=='ai.personal.companion.ios' and headers['apns-push-type']=='alert'
    assert payload['aps']['alert']['body']=='Ready'

def test_invalid_device_token_is_removed(tmp_path):
    registry=DeviceRegistry(tmp_path/'devices.sqlite3');device,_=registry.enroll('iPhone','ios');registry.set_metadata(device['id'],'push.apns.token','badtoken')
    p=APNsProvider(settings(),registry,client=Client(Response(410,'Unregistered')))
    r=p.send_device(device['id'],'Personal AI','Test')
    assert r.token_invalid and registry.metadata(device['id']).get('push.apns.token','')==''

def test_permission_gated_tool_remains_external_side_effect():
    from tools.registry import ToolRegistry,Risk
    from tools.notifications import register
    registry=ToolRegistry(SimpleNamespace(autonomy_mode='ask'));register(registry,APNsProvider(settings(),client=Client(Response())))
    tool=registry.get('notify_device');assert tool.risk==Risk.EXTERNAL_SIDE_EFFECT
    assert not registry.authorize(tool,confirmed=False).allowed
