from pathlib import Path
import shutil
from tools.registry import Tool, Risk

FORBIDDEN_NAMES = {'.env', 'vault.json', 'secrets.json', 'id_rsa', 'id_ed25519'}


def register(reg, settings=None):
    configured = tuple(getattr(settings, 'file_roots', ()) or ())
    roots = tuple(Path(item).expanduser().resolve() for item in configured)
    if not roots:
        data_dir = Path(getattr(settings, 'data_dir', Path.home() / '.personal_ai'))
        roots = ((data_dir / 'workspace').resolve(),)
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)

    def safe_path(raw, *, must_exist=False):
        path = Path(str(raw or roots[0])).expanduser().resolve()
        if not any(path == root or root in path.parents for root in roots):
            raise PermissionError('Path is outside owner-approved file roots')
        if any(part in FORBIDDEN_NAMES or part in {'.ssh', '.gnupg'} for part in path.parts):
            raise PermissionError('Secret-bearing paths are not available to tools')
        if must_exist and not path.exists():
            raise FileNotFoundError(path)
        return path

    def list_dir(p):
        path=safe_path(p.get('path') or roots[0], must_exist=True)
        if not path.is_dir():
            raise NotADirectoryError(path)
        return [{"name":x.name,"is_dir":x.is_dir(),"size":x.stat().st_size if x.is_file() else None}
                for x in list(path.iterdir())[:200] if x.name not in FORBIDDEN_NAMES]

    def read_file(p):
        path=safe_path(p['path'], must_exist=True)
        if not path.is_file():
            raise IsADirectoryError(path)
        return path.read_text(encoding="utf-8",errors="replace")[:50000]

    def write_file(p):
        path=safe_path(p['path'])
        if path.exists():
            raise FileExistsError('Use overwrite_file with explicit approval to replace an existing file')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(str(p.get("content","")),encoding="utf-8")
        return {"ok":True,"path":str(path)}

    def overwrite_file(p):
        path=safe_path(p['path'], must_exist=True)
        if not path.is_file():
            raise IsADirectoryError(path)
        path.write_text(str(p.get('content', '')), encoding='utf-8')
        return {'ok': True, 'path': str(path), 'overwritten': True}

    def copy_file(p):
        s=safe_path(p['source'], must_exist=True); d=safe_path(p['destination'])
        if d.exists():
            raise FileExistsError('Destination already exists')
        d.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(s,d)
        return {"ok":True,"destination":str(d)}

    reg.register(Tool("list_dir","List directory; params: path",list_dir,Risk.READ_ONLY))
    reg.register(Tool("read_file","Read text file; params: path",read_file,Risk.READ_ONLY))

    def legacy_mutation_disabled(_params):
        raise PermissionError('legacy file mutation is disabled; use the governed desktop_file_act authority')

    # Read compatibility remains bounded by owner-approved roots. Mutations are
    # compatibility-only names so all authoritative filesystem changes flow
    # through W7.5 trusted-context, durable transaction, verification/recovery.
    reg.register(Tool("write_file","Legacy file write (disabled)",legacy_mutation_disabled,Risk.REVERSIBLE,prohibited=True))
    reg.register(Tool("overwrite_file","Legacy file overwrite (disabled)",legacy_mutation_disabled,Risk.DESTRUCTIVE,prohibited=True))
    reg.register(Tool("copy_file","Legacy file copy (disabled)",legacy_mutation_disabled,Risk.REVERSIBLE,prohibited=True))
