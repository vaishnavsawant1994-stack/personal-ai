from __future__ import annotations
import base64, hashlib, json, secrets, time, urllib.parse, requests
from dataclasses import dataclass
from urllib.parse import urlparse

@dataclass
class OAuthProvider:
    id:str; authorize_url:str; token_url:str; client_id:str; scopes:list[str]; client_secret:str=''; revoke_url:str=''

class OAuthAccountManager:
    def __init__(self,vault,redirect_uri='http://127.0.0.1:8766/oauth/callback',*,state_store=None,allowed_redirects=None,security_epoch_provider=None,device_active=None,session_active=None):
        self.vault=vault; self.redirect_uri=redirect_uri; self._pending={}; self.state_store=state_store
        self.allowed_redirects=set(allowed_redirects or [redirect_uri]); self.security_epoch_provider=security_epoch_provider or (lambda:0)
        self.device_active=device_active; self.session_active=session_active
    @staticmethod
    def _challenge(verifier):return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    def _validate_redirect(self,uri):
        uri=str(uri or self.redirect_uri)
        if uri not in self.allowed_redirects: raise ValueError('OAuth redirect is not allowlisted')
        p=urlparse(uri)
        if p.scheme not in {'https','http'}: raise ValueError('OAuth redirect scheme is invalid')
        if p.scheme=='http' and p.hostname not in {'127.0.0.1','localhost'}: raise ValueError('OAuth redirect must use HTTPS')
        return uri
    def _existing_token_record(self,provider_id):
        try:
            raw=self.vault.get(f'oauth:{provider_id}')
            return json.loads(raw) if raw else {}
        except Exception:return {}
    @staticmethod
    def _scope_record(previous,token,requested):
        prev_confirmed=set(previous.get('confirmed_granted_scopes') or previous.get('granted_scopes') or [])
        raw_scope=token.get('scope')
        current=set(str(raw_scope).split()) if raw_scope else set(token.get('granted_scopes') or requested or [])
        confirmed=prev_confirmed|current
        reduced=sorted(prev_confirmed-current) if prev_confirmed and current else []
        token['granted_scopes']=sorted(current)
        token['confirmed_granted_scopes']=sorted(confirmed)
        token['scope_reduction_detected']=bool(reduced)
        token['reduced_scopes']=reduced
        return token
    def begin(self,p:OAuthProvider,*,owner_id='owner',device_id=None,session_id=None,connector_id=None,scopes=None,redirect_uri=None,security_epoch=None,relink_intent='connect',nonce=None)->dict:
        redirect=self._validate_redirect(redirect_uri); requested=list(scopes or p.scopes); state=secrets.token_urlsafe(32); verifier=secrets.token_urlsafe(48); challenge=self._challenge(verifier); nonce=nonce or secrets.token_urlsafe(24); epoch=int(self.security_epoch_provider() if security_epoch is None else security_epoch)
        if self.state_store:
            self.state_store.create_oauth(state=state,verifier=verifier,owner_id=owner_id,device_id=device_id,session_id=session_id,connector_id=connector_id or p.id,provider_id=p.id,scopes=requested,challenge=challenge,nonce=nonce,redirect_uri=redirect,security_epoch=epoch,relink_intent=relink_intent)
        else:self._pending[state]=(p,verifier,time.time()+600,redirect)
        q={'client_id':p.client_id,'redirect_uri':redirect,'response_type':'code','scope':' '.join(requested),'state':state,'code_challenge':challenge,'code_challenge_method':'S256','access_type':'offline','prompt':'consent','nonce':nonce}
        if p.id=='google':q['include_granted_scopes']='true'
        return {'state':state,'url':p.authorize_url+'?'+urllib.parse.urlencode(q),'expires_in':600,'connector_id':connector_id or p.id}
    def complete(self,state:str,code:str,provider:OAuthProvider|None=None,*,owner_id='owner',device_id=None,session_id=None,connector_id=None,security_epoch=None)->dict:
        if not code or len(str(code))>8192: raise ValueError('OAuth authorization code is invalid')
        epoch=int(self.security_epoch_provider() if security_epoch is None else security_epoch)
        if self.device_active and device_id and not self.device_active(device_id):
            if self.state_store:self.state_store.invalidate_device(device_id)
            raise PermissionError('OAuth device is no longer trusted')
        if self.session_active and session_id and not self.session_active(session_id):
            if self.state_store:self.state_store.invalidate_session(session_id)
            raise PermissionError('OAuth session is no longer active')
        if self.state_store:
            if provider is None: raise ValueError('OAuth provider is required for durable callback completion')
            item=self.state_store.consume_oauth(state=state,owner_id=owner_id,device_id=device_id,session_id=session_id,connector_id=connector_id or provider.id,provider_id=provider.id,security_epoch=epoch)
            verifier=item['verifier']; redirect=item['redirect_uri']; p=provider; requested=item['scopes']
        else:
            item=self._pending.pop(state,None)
            if not item or item[2]<time.time():raise ValueError('invalid or expired OAuth state')
            p,verifier,_,redirect=item; requested=p.scopes
        data={'grant_type':'authorization_code','code':code,'client_id':p.client_id,'redirect_uri':redirect,'code_verifier':verifier}
        if p.client_secret:data['client_secret']=p.client_secret
        try:
            r=requests.post(p.token_url,data=data,timeout=30); r.raise_for_status(); token=r.json()
        except Exception:
            if self.state_store:self.state_store.audit('oauth.failed',connector_id=connector_id or p.id,owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'provider':p.id,'reason':'token_exchange_failed'})
            raise
        if not isinstance(token,dict) or not token.get('access_token'): raise RuntimeError('OAuth provider returned no access token')
        previous=self._existing_token_record(p.id); token=self._scope_record(previous,token,requested); self._store(p.id,token)
        if self.state_store:
            health='insufficient_scope' if token.get('scope_reduction_detected') else 'healthy'
            self.state_store.set_health(connector_id or p.id,health,scopes=token['granted_scopes'],success=health=='healthy',error_code='scope_reduced' if health!='healthy' else None,error_message='Previously granted Google scopes are missing; reconnect before dispatch.' if health!='healthy' else None)
            self.state_store.audit('oauth.completed',connector_id=connector_id or p.id,owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'provider':p.id,'scopes':token['granted_scopes'],'confirmed_scope_union':token['confirmed_granted_scopes'],'scope_reduction_detected':bool(token.get('scope_reduction_detected'))})
            self.state_store.audit('connector.connected',connector_id=connector_id or p.id,owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'provider':p.id}); self.state_store.audit('scopes.granted',connector_id=connector_id or p.id,owner_id=owner_id,device_id=device_id,session_id=session_id,payload={'scopes':token['granted_scopes'],'confirmed_scope_union':token['confirmed_granted_scopes']})
        return {'connected':True,'provider':p.id,'scopes':token['granted_scopes'],'confirmed_scope_union':token['confirmed_granted_scopes'],'scope_reduction_detected':bool(token.get('scope_reduction_detected')),'reduced_scopes':token.get('reduced_scopes',[])}
    def _store(self,provider_id,token):self.vault.set(f'oauth:{provider_id}',json.dumps(token))
    def token_record(self,provider:OAuthProvider):
        raw=self.vault.get(f'oauth:{provider.id}')
        if not raw:raise KeyError(f'no account linked for {provider.id}')
        return json.loads(raw)
    def token(self,provider:OAuthProvider)->str:
        token=self.token_record(provider); expires_at=float(token.get('expires_at',0) or 0)
        if not expires_at and token.get('expires_in'):expires_at=time.time()+float(token['expires_in'])-30; token['expires_at']=expires_at; self._store(provider.id,token)
        if expires_at and expires_at<=time.time():token=self.refresh(provider,token)
        return token['access_token']
    def refresh(self,p:OAuthProvider,token:dict)->dict:
        refresh=token.get('refresh_token')
        if not refresh:
            if self.state_store:self.state_store.set_health(p.id,'authentication_required',error_code='refresh_token_unavailable',error_message='Reconnect the account')
            raise RuntimeError('refresh token unavailable; relink account')
        data={'grant_type':'refresh_token','refresh_token':refresh,'client_id':p.client_id}
        if p.client_secret:data['client_secret']=p.client_secret
        try:r=requests.post(p.token_url,data=data,timeout=30); r.raise_for_status(); fresh=r.json()
        except Exception:
            if self.state_store:
                self.state_store.set_health(p.id,'authentication_expired',error_code='refresh_failed',error_message='Account reconnect required'); self.state_store.audit('token.refresh_failed',connector_id=p.id,payload={'provider':p.id})
            raise
        fresh.setdefault('refresh_token',refresh); fresh['expires_at']=time.time()+float(fresh.get('expires_in',3600))-30; fresh=self._scope_record(token,fresh,token.get('granted_scopes',[])); self._store(p.id,fresh)
        if self.state_store:
            health='insufficient_scope' if fresh.get('scope_reduction_detected') else 'healthy'; self.state_store.set_health(p.id,health,scopes=fresh.get('granted_scopes',[]),success=health=='healthy',error_code='scope_reduced' if health!='healthy' else None,error_message='Previously granted Google scopes are missing; reconnect before dispatch.' if health!='healthy' else None); self.state_store.audit('token.refreshed',connector_id=p.id,payload={'provider':p.id,'scopes':fresh.get('granted_scopes',[]),'confirmed_scope_union':fresh.get('confirmed_granted_scopes',[])})
        return fresh
    def unlink(self,provider_id,*,provider:OAuthProvider|None=None,connector_id=None,owner_id='owner',device_id=None,session_id=None,attempt_provider_revocation=True):
        token=None
        try:
            raw=self.vault.get(f'oauth:{provider_id}'); token=json.loads(raw) if raw else None
        except Exception: token=None
        self.vault.delete(f'oauth:{provider_id}')
        rev='local_only'; health_id=connector_id or provider_id
        if self.state_store:self.state_store.set_health(health_id,'revoked',scopes=[],revocation_status='local_revoked'); self.state_store.audit('connector.locally_revoked',connector_id=health_id,owner_id=owner_id,device_id=device_id,session_id=session_id)
        if attempt_provider_revocation and provider and provider.revoke_url and token and token.get('access_token'):
            if self.state_store:self.state_store.audit('provider.revocation_attempted',connector_id=health_id,owner_id=owner_id,device_id=device_id,session_id=session_id)
            try:
                r=requests.post(provider.revoke_url,data={'token':token['access_token']},timeout=10); r.raise_for_status(); rev='confirmed'
                if self.state_store:self.state_store.set_health(health_id,'revoked',scopes=[],revocation_status='confirmed'); self.state_store.audit('provider.revocation_confirmed',connector_id=health_id,owner_id=owner_id,device_id=device_id,session_id=session_id)
            except Exception:
                rev='pending'
                if self.state_store:self.state_store.set_health(health_id,'revocation_pending',scopes=[],revocation_status='pending',error_code='provider_revocation_failed',error_message='Local access is revoked; provider confirmation is pending'); self.state_store.audit('provider.revocation_failed',connector_id=health_id,owner_id=owner_id,device_id=device_id,session_id=session_id)
        return {'revoked':True,'provider_revocation':rev}
