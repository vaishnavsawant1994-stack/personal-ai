from __future__ import annotations
import base64,hashlib,secrets,time,urllib.parse,requests
from dataclasses import dataclass

@dataclass
class OAuthProvider:
    id:str; authorize_url:str; token_url:str; client_id:str; scopes:list[str]; client_secret:str=''

class OAuthAccountManager:
    def __init__(self,vault,redirect_uri='http://127.0.0.1:8766/oauth/callback'):
        self.vault=vault; self.redirect_uri=redirect_uri; self._pending={}
    @staticmethod
    def _challenge(verifier):return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    def begin(self,p:OAuthProvider)->dict:
        state=secrets.token_urlsafe(24); verifier=secrets.token_urlsafe(48); self._pending[state]=(p,verifier,time.time()+600)
        q={'client_id':p.client_id,'redirect_uri':self.redirect_uri,'response_type':'code','scope':' '.join(p.scopes),'state':state,'code_challenge':self._challenge(verifier),'code_challenge_method':'S256','access_type':'offline','prompt':'consent'}
        return {'state':state,'url':p.authorize_url+'?'+urllib.parse.urlencode(q)}
    def complete(self,state:str,code:str)->dict:
        item=self._pending.pop(state,None)
        if not item or item[2]<time.time():raise ValueError('invalid or expired OAuth state')
        p,verifier,_=item; data={'grant_type':'authorization_code','code':code,'client_id':p.client_id,'redirect_uri':self.redirect_uri,'code_verifier':verifier}
        if p.client_secret:data['client_secret']=p.client_secret
        r=requests.post(p.token_url,data=data,timeout=30); r.raise_for_status(); token=r.json(); self._store(p.id,token); return token
    def _store(self,provider_id,token):
        import json; self.vault.set(f'oauth:{provider_id}',json.dumps(token))
    def token(self,provider:OAuthProvider)->str:
        import json; raw=self.vault.get(f'oauth:{provider.id}')
        if not raw:raise KeyError(f'no account linked for {provider.id}')
        token=json.loads(raw); expires_at=float(token.get('expires_at',0) or 0)
        if not expires_at and token.get('expires_in'):expires_at=time.time()+float(token['expires_in'])-30; token['expires_at']=expires_at; self._store(provider.id,token)
        if expires_at and expires_at<=time.time():token=self.refresh(provider,token)
        return token['access_token']
    def refresh(self,p:OAuthProvider,token:dict)->dict:
        refresh=token.get('refresh_token')
        if not refresh:raise RuntimeError('refresh token unavailable; relink account')
        data={'grant_type':'refresh_token','refresh_token':refresh,'client_id':p.client_id}
        if p.client_secret:data['client_secret']=p.client_secret
        r=requests.post(p.token_url,data=data,timeout=30); r.raise_for_status(); fresh=r.json(); fresh.setdefault('refresh_token',refresh); fresh['expires_at']=time.time()+float(fresh.get('expires_in',3600))-30; self._store(p.id,fresh); return fresh
    def unlink(self,provider_id):self.vault.delete(f'oauth:{provider_id}')
