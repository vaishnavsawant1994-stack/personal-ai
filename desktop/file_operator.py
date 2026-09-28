from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from security.policy_targets import TargetValidationError, canonical_path, validate_file_metadata


@dataclass(frozen=True)
class FileResult:
    status: str
    verified: bool
    rollback: str
    evidence: dict[str, Any]
    reason_code: str = 'allow'


class SafeFileAdapter:
    def __init__(self, *, max_bytes: int = 50 * 1024 * 1024):
        self.max_bytes=int(max_bytes)

    @staticmethod
    def checksum(path: str | os.PathLike) -> str:
        h=hashlib.sha256()
        with open(path,'rb') as fh:
            for chunk in iter(lambda:fh.read(1024*1024),b''): h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _reject_link_components(raw_path: str) -> None:
        raw=Path(str(raw_path)).expanduser()
        if not raw.is_absolute(): raw=Path.cwd()/raw
        parts=raw.parts
        current=Path(parts[0]) if parts else raw
        for part in parts[1:]:
            current=current/part
            try:
                if current.exists() and current.is_symlink():
                    raise TargetValidationError('path_changed','symlink traversal blocked')
            except OSError as exc:
                raise TargetValidationError('path_changed','path identity cannot be verified') from exc

    @staticmethod
    def _reject_reparse_or_mount(path: Path, roots: list[str]) -> None:
        try:
            st=path.lstat() if path.exists() else path.parent.lstat()
            attrs=getattr(st,'st_file_attributes',0)
            if attrs and attrs & 0x400:
                raise TargetValidationError('path_changed','junction/reparse target blocked')
            normalized_roots={str(Path(r).expanduser().resolve(strict=False)).casefold() for r in roots}
            if path.exists() and os.path.ismount(path) and str(path.resolve(strict=False)).casefold() not in normalized_roots:
                raise TargetValidationError('path_changed','mounted target requires explicit root policy')
        except TargetValidationError: raise
        except OSError as exc: raise TargetValidationError('path_changed','path identity cannot be verified') from exc

    @staticmethod
    def _reject_hardlink(path: Path) -> None:
        if not path.exists() or not path.is_file(): return
        try:
            if path.stat().st_nlink>1: raise TargetValidationError('path_changed','hard-linked file requires owner review')
        except TargetValidationError: raise
        except OSError as exc: raise TargetValidationError('path_changed','file identity cannot be verified') from exc

    @classmethod
    def _safe(cls,path: str, roots: list[str], *, must_exist=False, mutation=False) -> Path:
        cls._reject_link_components(path)
        canonical=canonical_path(path,roots)
        target=Path(canonical)
        if must_exist and not target.exists(): raise FileNotFoundError(canonical)
        cls._reject_reparse_or_mount(target,roots)
        if mutation: cls._reject_hardlink(target)
        return target

    @classmethod
    def _revalidate_parent(cls, path: Path, roots: list[str], expected_parent: Path, expected_identity=None) -> None:
        # Mutations must still target the same confined parent immediately
        # before commit. This closes parent-directory replacement races.
        cls._reject_link_components(str(path.parent))
        current=Path(canonical_path(str(path.parent),roots))
        cls._reject_reparse_or_mount(current,roots)
        try:
            b=current.stat()
            identity=expected_identity
            if identity is None:
                a=expected_parent.stat(); identity=(a.st_dev,a.st_ino)
            if tuple(identity)!=(b.st_dev,b.st_ino):
                raise TargetValidationError('path_changed','destination parent changed before mutation')
        except TargetValidationError: raise
        except OSError as exc:
            raise TargetValidationError('path_changed','destination parent identity cannot be verified') from exc

    @staticmethod
    def _free_space(path: Path) -> int:
        probe=path if path.exists() else path.parent
        return shutil.disk_usage(probe).free

    def metadata(self,path:str,roots:list[str])->dict[str,Any]:
        p=self._safe(path,roots,must_exist=True); st=p.stat()
        return {'exists':True,'name':p.name,'size':st.st_size,'is_file':p.is_file(),'is_dir':p.is_dir(),'sha256':self.checksum(p) if p.is_file() else '','link_count':st.st_nlink}

    def list_dir(self,path:str,roots:list[str],*,limit=500)->list[dict[str,Any]]:
        p=self._safe(path,roots,must_exist=True)
        if not p.is_dir(): raise NotADirectoryError(str(p))
        out=[]
        for child in sorted(p.iterdir(),key=lambda x:x.name.casefold())[:max(0,min(int(limit),500))]:
            if child.is_symlink(): continue
            out.append({'name':child.name,'is_file':child.is_file(),'is_dir':child.is_dir(),'size':child.stat().st_size if child.is_file() else 0})
        return out

    def read_text(self,path:str,roots:list[str],*,max_bytes=1024*1024)->str:
        p=self._safe(path,roots,must_exist=True)
        if not p.is_file(): raise IsADirectoryError(str(p))
        if p.stat().st_size>min(int(max_bytes),self.max_bytes): raise TargetValidationError('file_too_large','bounded file read exceeded')
        if p.suffix.lower() in {'.pdf','.doc','.docx','.ppt','.pptx','.xls','.xlsx','.zip','.exe','.dll','.png','.jpg','.jpeg'}:
            raise TargetValidationError('file_type_not_allowed','binary/structured documents must use Knowledge ingestion')
        return p.read_text(encoding='utf-8')

    def create_dir(self,path:str,roots:list[str])->FileResult:
        p=self._safe(path,roots)
        if p.exists(): raise FileExistsError('destination_exists')
        p.mkdir(parents=False)
        return FileResult('completed',p.is_dir(),'reversible',{'destination':str(p)})

    def create_file(self,path:str,roots:list[str],content:bytes|str=b'',*,claimed_mime='')->FileResult:
        p=self._safe(path,roots)
        if p.exists(): raise FileExistsError('destination_exists')
        data=content.encode('utf-8') if isinstance(content,str) else bytes(content)
        if len(data)>self.max_bytes: raise TargetValidationError('file_too_large','file exceeds configured limit')
        if self._free_space(p)<len(data)+1024*1024: raise OSError('insufficient_disk_space')
        parent=p.parent
        pst=parent.stat(); parent_identity=(pst.st_dev,pst.st_ino)
        fd,tmp=tempfile.mkstemp(prefix='.pai-',dir=str(parent)); os.close(fd); tmp_path=Path(tmp)
        try:
            tmp_path.write_bytes(data)
            self._revalidate_parent(p,roots,parent,parent_identity)
            if p.exists(): raise FileExistsError('destination_exists')
            os.replace(tmp_path,p)
            if claimed_mime: validate_file_metadata(str(p),claimed_mime=claimed_mime,max_bytes=self.max_bytes)
        except Exception:
            try: tmp_path.unlink(missing_ok=True)
            except Exception: pass
            try:
                if p.exists() and p.stat().st_size==len(data): p.unlink(missing_ok=True)
            except Exception: pass
            raise
        return FileResult('completed',p.exists(),'reversible',{'destination':str(p),'sha256':self.checksum(p),'size':p.stat().st_size})

    def copy(self,source:str,destination:str,roots:list[str],*,claimed_mime='')->FileResult:
        src=self._safe(source,roots,must_exist=True,mutation=True); dst=self._safe(destination,roots)
        if not src.is_file(): raise ValueError('source_not_regular_file')
        if dst.exists(): raise FileExistsError('destination_exists')
        validate_file_metadata(str(src),claimed_mime=claimed_mime,max_bytes=self.max_bytes)
        source_hash=self.checksum(src); size=src.stat().st_size
        if self._free_space(dst)<size+1024*1024: raise OSError('insufficient_disk_space')
        parent=dst.parent
        pst=parent.stat(); parent_identity=(pst.st_dev,pst.st_ino)
        fd,tmp=tempfile.mkstemp(prefix='.pai-copy-',dir=str(parent)); os.close(fd); tmp_path=Path(tmp)
        try:
            with src.open('rb') as r,tmp_path.open('wb') as w: shutil.copyfileobj(r,w,1024*1024)
            if self.checksum(src)!=source_hash: raise PermissionError('path_changed')
            if self.checksum(tmp_path)!=source_hash: raise IOError('checksum_mismatch')
            self._revalidate_parent(dst,roots,parent,parent_identity)
            if dst.exists(): raise FileExistsError('destination_exists')
            os.replace(tmp_path,dst)
        except Exception:
            try: tmp_path.unlink(missing_ok=True)
            except Exception: pass
            raise
        return FileResult('completed',dst.exists() and self.checksum(dst)==source_hash,'reversible',{'source_sha256':source_hash,'destination_sha256':self.checksum(dst),'destination':str(dst)})

    def move(self,source:str,destination:str,roots:list[str])->FileResult:
        src=self._safe(source,roots,must_exist=True,mutation=True); dst=self._safe(destination,roots)
        if dst.exists(): raise FileExistsError('destination_exists')
        source_hash=self.checksum(src) if src.is_file() else ''
        parent=dst.parent
        pst=parent.stat(); parent_identity=(pst.st_dev,pst.st_ino)
        self._revalidate_parent(dst,roots,parent,parent_identity)
        if dst.exists(): raise FileExistsError('destination_exists')
        os.replace(src,dst)
        ok=dst.exists() and not src.exists() and (not source_hash or self.checksum(dst)==source_hash)
        return FileResult('completed',ok,'reversible',{'source_sha256':source_hash,'destination':str(dst)})

    def rename(self,source:str,destination:str,roots:list[str])->FileResult:
        return self.move(source,destination,roots)

    def trash(self,path:str,roots:list[str],trash_root:str)->FileResult:
        src=self._safe(path,roots,must_exist=True,mutation=True); tr=self._safe(trash_root,roots,must_exist=True)
        if not tr.is_dir(): raise NotADirectoryError(str(tr))
        candidate=tr/src.name; n=1
        while candidate.exists(): candidate=tr/f'{src.stem} ({n}){src.suffix}'; n+=1
        source_hash=self.checksum(src) if src.is_file() else ''
        pst=tr.stat(); parent_identity=(pst.st_dev,pst.st_ino)
        self._revalidate_parent(candidate,roots,tr,parent_identity)
        if candidate.exists(): raise FileExistsError('destination_exists')
        os.replace(src,candidate)
        return FileResult('completed',candidate.exists() and not src.exists(),'compensating_action_available',{'trash_path':str(candidate),'source_sha256':source_hash})

    def permanent_delete(self,path:str,roots:list[str])->FileResult:
        target=self._safe(path,roots,must_exist=True,mutation=True)
        if target.is_dir():
            if any(target.iterdir()): raise OSError('non_empty_directory_delete_blocked')
            target.rmdir()
        else: target.unlink()
        return FileResult('completed',not target.exists(),'irreversible',{'target_absent':not target.exists(),'no_rollback':True})
