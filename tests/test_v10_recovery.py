from pathlib import Path
import json,sqlite3,zipfile
import pytest
from recovery.backup import BackupService,BackupError

def test_backup_excludes_secrets_and_restores(tmp_path):
    data=tmp_path/'data';data.mkdir();(data/'note.txt').write_text('hello');(data/'vault.json').write_text('secret');(data/'.env').write_text('TOKEN=x')
    db=data/'assistant.sqlite3'
    with sqlite3.connect(db) as c:c.execute('create table t(v text)');c.execute('insert into t values(?)',('before',))
    svc=BackupService(data);archive=svc.create('test.paibackup');manifest=svc.inspect(archive);paths={x['path'] for x in manifest['files']}
    assert 'note.txt' in paths and 'assistant.sqlite3' in paths and 'vault.json' not in paths and '.env' not in paths
    (data/'note.txt').write_text('changed');svc.restore(archive);assert (data/'note.txt').read_text()=='hello'
    assert (data/'vault.json').read_text()=='secret'

def test_backup_detects_tampering(tmp_path):
    data=tmp_path/'data';data.mkdir();(data/'a.txt').write_text('A');svc=BackupService(data);archive=svc.create('x.paibackup')
    corrupt=tmp_path/'bad.paibackup'
    with zipfile.ZipFile(archive) as src,zipfile.ZipFile(corrupt,'w') as out:
        for info in src.infolist():out.writestr(info,'B' if info.filename=='a.txt' else src.read(info.filename))
    with pytest.raises(BackupError):svc.inspect(corrupt)

def test_backup_rejects_traversal(tmp_path):
    archive=tmp_path/'bad.paibackup'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape.txt','x');z.writestr('manifest.json',json.dumps({'files':[]}))
    with pytest.raises(BackupError):BackupService(tmp_path/'data').inspect(archive)
