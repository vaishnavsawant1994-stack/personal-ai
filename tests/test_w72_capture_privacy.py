import io
import os
import sys
import threading
import time
from types import SimpleNamespace

from PIL import Image
import pytest

from vision.screen_understanding import ScreenUnderstanding


class _MSS:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    @property
    def monitors(self): return [{'left':0,'top':0,'width':20,'height':20},{'left':0,'top':0,'width':20,'height':20}]
    def grab(self, mon): return SimpleNamespace(size=(20,20), rgb=b'\xff'*(20*20*3))


def _install(monkeypatch): monkeypatch.setitem(sys.modules,'mss',SimpleNamespace(mss=lambda:_MSS()))


def test_missing_mapping_persists_only_full_frame_fallback(tmp_path, monkeypatch):
    _install(monkeypatch); screen=ScreenUnderstanding(None,tmp_path)
    record=screen.observe_record(redactions=None)
    assert record['redaction_status']=='full_frame_redacted' and record['visual_evidence_unavailable'] is True
    with Image.open(tmp_path/record['screenshot_evidence_ref']) as image: assert image.getpixel((2,2))==(0,0,0)


def test_unavailable_visual_evidence_is_not_sent_to_model(tmp_path, monkeypatch):
    _install(monkeypatch)
    class Models:
        def __init__(self): self.calls=0
        def vision(self,prompt,image): self.calls+=1; return 'unexpected'
    models=Models(); result=ScreenUnderstanding(models,tmp_path).analyze(redactions=None)
    assert models.calls==0 and result['visual_evidence_unavailable'] is True


def test_browser_sanitized_bytes_are_the_only_model_image(tmp_path):
    buffer=io.BytesIO(); Image.new('RGB',(4,4),'black').save(buffer,format='PNG')
    class Models:
        def __init__(self): self.image=''
        def vision(self,prompt,image): self.image=image; return 'VERIFIED sanitized'
    models=Models(); source={'available':True,'redaction_status':'sanitized','redaction_method':'browser_native_element_mask','sensitive_count':1,'bytes':buffer.getvalue(),'capture_source':'browser_native','geometry':{}}
    result=ScreenUnderstanding(models,tmp_path).analyze(sanitized_source=source,evidence_binding={'owner_id':'o','device_id':'d','session_id':'s'})
    assert result['redaction_status']=='sanitized' and models.image.startswith('data:image/png;base64,')


def test_concurrent_captures_use_unique_evidence_ids(tmp_path, monkeypatch):
    _install(monkeypatch); screen=ScreenUnderstanding(None,tmp_path); ids=[]; errors=[]
    def worker():
        try: ids.append(screen.observe_record(redactions=[])['evidence_id'])
        except Exception as exc: errors.append(exc)
    threads=[threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert not errors and len(ids)==6 and len(set(ids))==6


def test_retention_removes_old_sanitized_evidence(tmp_path, monkeypatch):
    _install(monkeypatch); screen=ScreenUnderstanding(None,tmp_path); first=screen.observe_record(redactions=[]); path=tmp_path/first['screenshot_evidence_ref']
    old=time.time()-1000; os.utime(path,(old,old)); screen.retention_seconds=1; screen.observe_record(redactions=[])
    assert not path.exists()


def test_evidence_directory_symlink_and_bad_identifier_are_rejected(tmp_path, monkeypatch):
    _install(monkeypatch); target=tmp_path/'target'; target.mkdir(); (tmp_path/'screenshots').symlink_to(target,target_is_directory=True); screen=ScreenUnderstanding(None,tmp_path)
    with pytest.raises(PermissionError): screen.observe_record(redactions=[])
    (tmp_path/'screenshots').unlink()
    with pytest.raises(ValueError): screen._secure_write(b'x','bad/path')
