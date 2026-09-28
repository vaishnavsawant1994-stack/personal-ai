from pathlib import Path
import os
import pytest

from desktop.file_operator import SafeFileAdapter
from security.policy_targets import TargetValidationError


def test_metadata_and_checksum(tmp_path):
    f=tmp_path/'a.txt';f.write_text('hello');op=SafeFileAdapter();m=op.metadata(str(f),[str(tmp_path)])
    assert m['size']==5 and len(m['sha256'])==64 and op.checksum(f)==m['sha256']

def test_read_text_rejects_binary_document(tmp_path):
    f=tmp_path/'x.pdf';f.write_bytes(b'%PDF-1.4');op=SafeFileAdapter()
    with pytest.raises(TargetValidationError) as e:op.read_text(str(f),[str(tmp_path)])
    assert e.value.reason_code=='file_type_not_allowed'

def test_read_text_size_limit(tmp_path):
    f=tmp_path/'big.txt';f.write_bytes(b'x'*20)
    with pytest.raises(TargetValidationError):SafeFileAdapter().read_text(str(f),[str(tmp_path)],max_bytes=10)

def test_create_file_no_overwrite(tmp_path):
    f=tmp_path/'a.txt';f.write_text('old')
    with pytest.raises(FileExistsError):SafeFileAdapter().create_file(str(f),[str(tmp_path)],'new')
    assert f.read_text()=='old'

def test_create_file_verified(tmp_path):
    f=tmp_path/'a.txt';r=SafeFileAdapter().create_file(str(f),[str(tmp_path)],'hello')
    assert r.verified and r.rollback=='reversible' and f.read_text()=='hello'

def test_copy_checksum_and_no_blind_overwrite(tmp_path):
    s=tmp_path/'s.txt';d=tmp_path/'d.txt';s.write_text('abc');op=SafeFileAdapter();r=op.copy(str(s),str(d),[str(tmp_path)])
    assert r.verified and r.evidence['source_sha256']==r.evidence['destination_sha256']
    with pytest.raises(FileExistsError):op.copy(str(s),str(d),[str(tmp_path)])

def test_move_verified_source_absent(tmp_path):
    s=tmp_path/'s.txt';d=tmp_path/'d.txt';s.write_text('abc');r=SafeFileAdapter().move(str(s),str(d),[str(tmp_path)])
    assert r.verified and d.exists() and not s.exists()

def test_trash_retains_recovery_metadata(tmp_path):
    trash=tmp_path/'trash';trash.mkdir();f=tmp_path/'x.txt';f.write_text('x');r=SafeFileAdapter().trash(str(f),[str(tmp_path)],str(trash))
    assert r.verified and r.rollback=='compensating_action_available' and Path(r.evidence['trash_path']).exists()

def test_permanent_delete_truthfully_irreversible(tmp_path):
    f=tmp_path/'x.txt';f.write_text('x');r=SafeFileAdapter().permanent_delete(str(f),[str(tmp_path)])
    assert r.verified and r.rollback=='irreversible' and r.evidence['no_rollback'] is True

def test_nonempty_directory_permanent_delete_blocked(tmp_path):
    d=tmp_path/'d';d.mkdir();(d/'x').write_text('x')
    with pytest.raises(OSError):SafeFileAdapter().permanent_delete(str(d),[str(tmp_path)])

def test_path_escape_blocked(tmp_path):
    with pytest.raises(TargetValidationError):SafeFileAdapter().metadata(str(tmp_path/'..'/'escape'),[str(tmp_path)])

def test_symlink_swap_blocked_before_resolution(tmp_path):
    target=tmp_path/'target';target.mkdir();link=tmp_path/'link'
    try:link.symlink_to(target,target_is_directory=True)
    except OSError:pytest.skip('symlink unavailable')
    with pytest.raises(TargetValidationError) as exc:SafeFileAdapter().metadata(str(link),[str(tmp_path)])
    assert exc.value.reason_code=='path_changed'

def test_hard_link_mutation_requires_review(tmp_path):
    source=tmp_path/'a.txt';other=tmp_path/'b.txt';dest=tmp_path/'c.txt';source.write_text('x')
    try:os.link(source,other)
    except OSError:pytest.skip('hard links unavailable')
    with pytest.raises(TargetValidationError) as exc:SafeFileAdapter().move(str(source),str(dest),[str(tmp_path)])
    assert exc.value.reason_code=='path_changed'

def test_destination_collision_never_overwrites(tmp_path):
    src=tmp_path/'src.txt';dst=tmp_path/'dst.txt';src.write_text('new');dst.write_text('old')
    with pytest.raises(FileExistsError):SafeFileAdapter().copy(str(src),str(dst),[str(tmp_path)])
    assert dst.read_text()=='old'


def test_parent_identity_revalidation_detects_replacement(tmp_path):
    root=tmp_path/'root';root.mkdir()
    parent=root/'parent';parent.mkdir()
    destination=parent/'out.txt'
    expected_parent=parent.resolve()
    st=expected_parent.stat(); expected_identity=(st.st_dev,st.st_ino)
    original=root/'parent-authorized'
    parent.rename(original)
    parent.mkdir()
    with pytest.raises(TargetValidationError) as exc:
        SafeFileAdapter._revalidate_parent(destination,[str(root)],expected_parent,expected_identity)
    assert exc.value.reason_code=='path_changed'


def test_move_revalidates_destination_parent_before_replace(tmp_path, monkeypatch):
    root=tmp_path/'root';root.mkdir();src=root/'src.txt';src.write_text('x')
    parent=root/'dest';parent.mkdir();dst=parent/'out.txt'
    original=SafeFileAdapter._revalidate_parent
    def substitute(cls,path,roots,expected_parent,expected_identity=None):
        moved=root/'dest-authorized'
        parent.rename(moved);parent.mkdir()
        return original(path,roots,expected_parent,expected_identity)
    monkeypatch.setattr(SafeFileAdapter,'_revalidate_parent',classmethod(substitute))
    with pytest.raises(TargetValidationError) as exc:
        SafeFileAdapter().move(str(src),str(dst),[str(root)])
    assert exc.value.reason_code=='path_changed'
    assert src.exists() and not dst.exists()

def test_trash_revalidates_destination_parent_before_replace(tmp_path, monkeypatch):
    root=tmp_path/'root';root.mkdir();src=root/'src.txt';src.write_text('x')
    trash=root/'trash';trash.mkdir()
    original=SafeFileAdapter._revalidate_parent
    def substitute(cls,path,roots,expected_parent,expected_identity=None):
        moved=root/'trash-authorized'
        trash.rename(moved);trash.mkdir()
        return original(path,roots,expected_parent,expected_identity)
    monkeypatch.setattr(SafeFileAdapter,'_revalidate_parent',classmethod(substitute))
    with pytest.raises(TargetValidationError) as exc:
        SafeFileAdapter().trash(str(src),[str(root)],str(trash))
    assert exc.value.reason_code=='path_changed'
    assert src.exists()
