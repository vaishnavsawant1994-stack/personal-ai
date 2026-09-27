from __future__ import annotations
import base64,json,time
from dataclasses import dataclass
from typing import Any
import httpx
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


def _b64url(data:bytes)->str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')

@dataclass
class APNsResult:
    ok:bool
    status:int
    reason:str=''
    apns_id:str=''
    retryable:bool=False
    token_invalid:bool=False
    def as_dict(self):return self.__dict__.copy()

class APNsProvider:
    """Token-authenticated Apple Push Notification service provider over HTTP/2."""
    def __init__(self,settings,device_registry=None,events=None,client:Any=None):
        self.settings=settings;self.device_registry=device_registry;self.events=events
        self.client=client or httpx.Client(http2=True,timeout=15.0)
        self._jwt='';self._jwt_issued=0
    @property
    def configured(self)->bool:
        return bool(self.settings.apns_team_id and self.settings.apns_key_id and self.settings.apns_private_key_b64 and self.settings.apns_topic)
    @property
    def base_url(self)->str:
        return 'https://api.push.apple.com' if self.settings.apns_environment=='production' else 'https://api.sandbox.push.apple.com'
    def _private_key(self):
        try:pem=base64.b64decode(self.settings.apns_private_key_b64)
        except Exception as e:raise RuntimeError('APNS_PRIVATE_KEY_B64 is invalid base64') from e
        key=serialization.load_pem_private_key(pem,password=None)
        if not isinstance(key,ec.EllipticCurvePrivateKey):raise RuntimeError('APNs key must be an EC private key')
        return key
    def provider_token(self,now:int|None=None)->str:
        now=int(time.time() if now is None else now)
        if self._jwt and now-self._jwt_issued<50*60:return self._jwt
        if not self.configured:raise RuntimeError('APNs provider is not configured')
        header=_b64url(json.dumps({'alg':'ES256','kid':self.settings.apns_key_id},separators=(',',':')).encode())
        payload=_b64url(json.dumps({'iss':self.settings.apns_team_id,'iat':now},separators=(',',':')).encode())
        signing=f'{header}.{payload}'.encode('ascii')
        der=self._private_key().sign(signing,ec.ECDSA(hashes.SHA256()));r,s=decode_dss_signature(der)
        raw=r.to_bytes(32,'big')+s.to_bytes(32,'big')
        self._jwt=f'{header}.{payload}.{_b64url(raw)}';self._jwt_issued=now;return self._jwt
    def _payload(self,title:str,body:str,*,data:dict|None=None,badge:int|None=None,sound:str|None='default')->dict:
        alert={'title':str(title)[:120],'body':str(body)[:500]};aps={'alert':alert}
        if badge is not None:aps['badge']=int(badge)
        if sound:aps['sound']=sound
        payload={'aps':aps}
        if data:payload['personal_ai']=data
        encoded=json.dumps(payload,separators=(',',':')).encode('utf-8')
        if len(encoded)>4096:raise ValueError('APNs payload exceeds 4096-byte limit')
        return payload
    def send_token(self,token:str,title:str,body:str,*,data:dict|None=None,badge:int|None=None,sound:str|None='default',collapse_id:str|None=None)->APNsResult:
        if not self.configured:return APNsResult(False,0,'not_configured')
        token=(token or '').strip()
        if not token:return APNsResult(False,0,'missing_device_token')
        headers={'authorization':f'bearer {self.provider_token()}','apns-topic':self.settings.apns_topic,'apns-push-type':'alert','apns-priority':'10'}
        if collapse_id:headers['apns-collapse-id']=collapse_id[:64]
        try:r=self.client.post(f'{self.base_url}/3/device/{token}',headers=headers,json=self._payload(title,body,data=data,badge=badge,sound=sound))
        except (httpx.TimeoutException,httpx.NetworkError) as e:return APNsResult(False,0,type(e).__name__,retryable=True)
        reason=''
        try:reason=(r.json() or {}).get('reason','') if r.content else ''
        except Exception:reason=r.text[:200]
        ok=r.status_code==200;invalid=r.status_code==410 or reason in {'BadDeviceToken','Unregistered','DeviceTokenNotForTopic'}
        retryable=r.status_code in {429,500,503}
        result=APNsResult(ok,r.status_code,reason,r.headers.get('apns-id',''),retryable,invalid)
        self._emit('notification.apns.delivery',status=r.status_code,reason=reason,ok=ok,retryable=retryable)
        return result
    def send_device(self,device_id:str,title:str,body:str,**kwargs)->APNsResult:
        if not self.device_registry:return APNsResult(False,0,'device_registry_unavailable')
        meta=self.device_registry.metadata(device_id);token=meta.get('push.apns.token','')
        result=self.send_token(token,title,body,**kwargs)
        if result.token_invalid:self.device_registry.set_metadata(device_id,'push.apns.token','')
        return result
    def _emit(self,name:str,**payload):
        if not self.events:return
        try:self.events.emit(name,**payload)
        except TypeError:
            try:self.events.publish(name,payload)
            except Exception:pass
    def close(self):
        close=getattr(self.client,'close',None)
        if close:close()
