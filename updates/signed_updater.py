from __future__ import annotations
import base64,hashlib,json,shutil,tempfile,zipfile
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
class UpdateVerificationError(RuntimeError):pass
class SignedUpdater:
    def __init__(self,public_key_b64:str,install_dir:Path):self.public_key=Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64));self.install_dir=Path(install_dir)
    def verify_manifest(self,manifest_bytes:bytes,signature_b64:str)->dict:
        try:self.public_key.verify(base64.b64decode(signature_b64),manifest_bytes)
        except Exception as e:raise UpdateVerificationError('manifest signature invalid') from e
        value=json.loads(manifest_bytes)
        if not isinstance(value,dict) or not isinstance(value.get('artifacts',[]),list):raise UpdateVerificationError('manifest structure invalid')
        return value
    @staticmethod
    def verify_file(path:Path,expected_sha256:str):
        h=hashlib.sha256()
        with open(path,'rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        if h.hexdigest().lower()!=expected_sha256.lower():raise UpdateVerificationError('package hash mismatch')
    def stage_zip(self,zip_path:Path,expected_sha256:str)->Path:
        self.verify_file(zip_path,expected_sha256);stage=Path(tempfile.mkdtemp(prefix='personal-ai-update-'));root=stage.resolve()
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                dest=(root/info.filename).resolve()
                if root not in dest.parents and dest!=root:raise UpdateVerificationError('unsafe zip path')
                if info.is_dir():continue
                if info.external_attr>>16 & 0o170000==0o120000:raise UpdateVerificationError('symbolic links are not allowed in updates')
            z.extractall(stage)
        return stage
    def install_staged(self,stage:Path):
        stage=Path(stage).resolve();backup=self.install_dir.with_name(self.install_dir.name+'.backup')
        if backup.exists():shutil.rmtree(backup)
        if self.install_dir.exists():shutil.copytree(self.install_dir,backup)
        try:
            self.install_dir.mkdir(parents=True,exist_ok=True)
            for src in stage.rglob('*'):
                rel=src.relative_to(stage);dst=self.install_dir/rel
                if src.is_dir():dst.mkdir(parents=True,exist_ok=True)
                else:dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        except Exception:
            self.rollback(backup);raise
        return backup
    def rollback(self,backup:Path):
        backup=Path(backup)
        if not backup.exists():raise FileNotFoundError('update backup does not exist')
        restore=self.install_dir.with_name(self.install_dir.name+'.restore-tmp')
        if restore.exists():shutil.rmtree(restore)
        shutil.copytree(backup,restore)
        if self.install_dir.exists():shutil.rmtree(self.install_dir)
        restore.replace(self.install_dir)
        return self.install_dir
