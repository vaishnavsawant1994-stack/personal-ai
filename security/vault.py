from __future__ import annotations
import base64,json,os,secrets
from pathlib import Path
from threading import RLock
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from security.keychain import RootKeyStore

class SecretVault:
    VERSION=2
    def __init__(self,path:Path,password:str|None=None,root_key_store:RootKeyStore|None=None):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.lock=RLock(); self._data={}; self._salt=b''; self._password=password.encode() if password else None; self.root_key_store=root_key_store or RootKeyStore()
        if self.path.exists():self._load()
        else:self._salt=secrets.token_bytes(16); self._save()
    def _master(self)->bytes:
        if self._password:return Scrypt(salt=self._salt,length=32,n=2**14,r=8,p=1).derive(self._password)
        return self.root_key_store.get_or_create()
    def _load(self):
        obj=json.loads(self.path.read_text()); version=int(obj.get('version',1)); self._salt=base64.b64decode(obj['salt']); nonce=base64.b64decode(obj['nonce']); ct=base64.b64decode(obj['ciphertext']); aad=f'personal-ai-vault-v{version}'.encode(); self._data=json.loads(AESGCM(self._master()).decrypt(nonce,ct,aad).decode())
    def _save(self):
        nonce=secrets.token_bytes(12); raw=json.dumps(self._data,sort_keys=True,separators=(',',':')).encode(); aad=f'personal-ai-vault-v{self.VERSION}'.encode(); ct=AESGCM(self._master()).encrypt(nonce,raw,aad); tmp=self.path.with_suffix(self.path.suffix+'.tmp'); tmp.write_text(json.dumps({'version':self.VERSION,'salt':base64.b64encode(self._salt).decode(),'nonce':base64.b64encode(nonce).decode(),'ciphertext':base64.b64encode(ct).decode()})); os.replace(tmp,self.path)
    def set(self,name:str,value:str):
        with self.lock:self._data[name]=value; self._save()
    def get(self,name:str,default=None):return self._data.get(name,default)
    def delete(self,name:str):
        with self.lock:self._data.pop(name,None); self._save()
    def names(self):return sorted(self._data)
    def rotate_password(self,new_password:str):
        with self.lock:
            self._password=new_password.encode(); self._salt=secrets.token_bytes(16); self._save()
    def rotate_root_key(self):
        if self._password:raise RuntimeError('vault is password-backed')
        with self.lock:
            data=dict(self._data); self.root_key_store.rotate(); self._data=data; self._salt=secrets.token_bytes(16); self._save()
    def migrate_to_keychain(self):
        with self.lock:self._password=None; self._salt=secrets.token_bytes(16); self.root_key_store.get_or_create(); self._save()
