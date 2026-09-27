from __future__ import annotations
import hashlib,json,shutil,sqlite3,tempfile,time,zipfile
from pathlib import Path

EXCLUDED_NAMES={'vault.json','.env','secrets.json'}
EXCLUDED_DIRS={'browser-profile','cache','tmp'}
class BackupError(RuntimeError):pass

class BackupService:
    """Creates integrity-checked Personal AI data backups without exporting secret stores."""
    def __init__(self,data_dir:Path):
        self.data_dir=Path(data_dir).resolve();self.backup_dir=self.data_dir/'backups';self.backup_dir.mkdir(parents=True,exist_ok=True)
    @staticmethod
    def _sha(path:Path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        return h.hexdigest()
    def _eligible(self):
        files=[]
        for path in self.data_dir.rglob('*'):
            if not path.is_file():continue
            if self.backup_dir in path.parents:continue
            rel=path.relative_to(self.data_dir)
            if path.name in EXCLUDED_NAMES:continue
            if any(part.lower() in EXCLUDED_DIRS for part in rel.parts[:-1]):continue
            files.append(path)
        return sorted(files)
    def create(self,name:str|None=None)->Path:
        stamp=time.strftime('%Y%m%d-%H%M%S');target=self.backup_dir/(name or f'personal-ai-{stamp}.paibackup')
        if target.suffix!='.paibackup':target=target.with_suffix('.paibackup')
        manifest={'version':1,'created_at':time.time(),'files':[],'excludes':sorted(EXCLUDED_NAMES)}
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for src in self._eligible():
                rel=src.relative_to(self.data_dir).as_posix();z.write(src,rel);manifest['files'].append({'path':rel,'sha256':self._sha(src),'size':src.stat().st_size})
            z.writestr('manifest.json',json.dumps(manifest,sort_keys=True,indent=2))
        return target
    def inspect(self,archive:Path)->dict:
        archive=Path(archive)
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist();names={i.filename for i in infos if not i.is_dir()}
            for info in infos:
                if info.is_dir():continue
                p=Path(info.filename)
                if p.is_absolute() or '..' in p.parts:raise BackupError('unsafe backup path')
            try:manifest=json.loads(z.read('manifest.json'))
            except Exception as exc:raise BackupError('backup manifest missing or invalid') from exc
            if manifest.get('version')!=1 or not isinstance(manifest.get('files'),list):raise BackupError('unsupported backup manifest')
            listed={x['path']:x for x in manifest['files']};expected=set(listed)|{'manifest.json'}
            if names!=expected:raise BackupError('backup contains unlisted or missing payloads')
            for rel,item in listed.items():
                if Path(rel).name in EXCLUDED_NAMES:raise BackupError('backup contains forbidden secret file')
                data=z.read(rel)
                if len(data)!=int(item['size']):raise BackupError(f'backup size mismatch: {rel}')
                if hashlib.sha256(data).hexdigest()!=item['sha256']:raise BackupError(f'backup integrity failure: {rel}')
            return manifest
    def restore(self,archive:Path)->dict:
        manifest=self.inspect(archive);stage=Path(tempfile.mkdtemp(prefix='personal-ai-restore-'))
        try:
            with zipfile.ZipFile(archive) as z:
                for item in manifest['files']:
                    rel=Path(item['path']);dest=(stage/rel).resolve()
                    if stage.resolve() not in dest.parents:raise BackupError('unsafe restore path')
                    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(item['path']))
            for item in manifest['files']:
                rel=Path(item['path']);src=stage/rel;dest=self.data_dir/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                if dest.suffix in {'.sqlite3','.db'}:
                    with sqlite3.connect(src) as c:
                        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise BackupError(f'database integrity failure: {rel}')
                shutil.copy2(src,dest)
            return {'ok':True,'restored':len(manifest['files']),'created_at':manifest['created_at']}
        finally:shutil.rmtree(stage,ignore_errors=True)
