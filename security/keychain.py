from __future__ import annotations
import base64,os,secrets

SERVICE='PersonalAI.RootKey'
ACCOUNT='default'
ENV_ROOT_KEY='PERSONAL_AI_ROOT_KEY'

class KeychainUnavailable(RuntimeError): pass

class RootKeyStore:
    def __init__(self,service:str=SERVICE,account:str=ACCOUNT): self.service=service; self.account=account
    def _env_key(self)->bytes|None:
        raw=os.getenv(ENV_ROOT_KEY,'').strip()
        if not raw:return None
        try:key=base64.b64decode(raw,validate=True)
        except Exception as e:raise KeychainUnavailable(f'{ENV_ROOT_KEY} must be valid base64') from e
        if len(key)!=32:raise KeychainUnavailable(f'{ENV_ROOT_KEY} must decode to exactly 32 bytes')
        return key
    def _kr(self):
        try: import keyring; return keyring
        except Exception as e: raise KeychainUnavailable('OS keychain backend unavailable') from e
    def get(self)->bytes|None:
        env_key=self._env_key()
        if env_key:return env_key
        try:raw=self._kr().get_password(self.service,self.account)
        except Exception as e:raise KeychainUnavailable('OS keychain backend unavailable and PERSONAL_AI_ROOT_KEY is not configured') from e
        return base64.b64decode(raw) if raw else None
    def get_or_create(self)->bytes:
        key=self.get()
        if key:return key
        key=secrets.token_bytes(32)
        try:self._kr().set_password(self.service,self.account,base64.b64encode(key).decode())
        except Exception as e:raise KeychainUnavailable('OS keychain backend cannot persist root key; configure PERSONAL_AI_ROOT_KEY for headless/cloud runtime') from e
        return key
    def rotate(self)->bytes:
        if self._env_key():raise KeychainUnavailable('Cannot rotate an environment-managed root key in-process')
        key=secrets.token_bytes(32); self._kr().set_password(self.service,self.account,base64.b64encode(key).decode()); return key
    def delete(self):
        if self._env_key():return
        try:self._kr().delete_password(self.service,self.account)
        except Exception:pass
