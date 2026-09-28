from __future__ import annotations

import hashlib
import io
import sys
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from browser.session import PersistentBrowser
from desktop.evidence_geometry import COORDINATE_SPACE_VERSION, CoordinateSpace, GeometryContext, GeometryError, Rect, clip_rect, transform_sensitive_rectangles
from vision.screen_understanding import EvidenceGuardError, SanitizedEvidenceGuard, ScreenUnderstanding


def geometry(**overrides):
    base = dict(device_pixel_ratio=1.0,page_zoom=1.0,viewport_width=800,viewport_height=600,scroll_x=0,scroll_y=0,browser_window_x=100,browser_window_y=50,browser_window_width=900,browser_window_height=700,content_offset_x=8,content_offset_y=72,monitor_x=0,monitor_y=0,monitor_width=1920,monitor_height=1080,monitor_scale=1.0,virtual_origin_x=0,virtual_origin_y=0,screenshot_origin_x=0,screenshot_origin_y=0,screenshot_width=1920,screenshot_height=1080,capture_source='desktop_monitor')
    base.update(overrides); return GeometryContext(**base)


@pytest.mark.parametrize('dpr',[1.0,2.0,3.0])
def test_viewport_mapping_accounts_for_device_pixel_ratio(dpr):
    out=transform_sensitive_rectangles([Rect(10,20,30,40,CoordinateSpace.BROWSER_VIEWPORT)],geometry(device_pixel_ratio=dpr))[0]
    assert out.width==pytest.approx(30*dpr) and out.height==pytest.approx(40*dpr)


def test_browser_zoom_changes_content_scale_without_scaling_window_origin():
    out=transform_sensitive_rectangles([Rect(10,10,20,20,CoordinateSpace.BROWSER_VIEWPORT)],geometry(device_pixel_ratio=2,page_zoom=1.5,monitor_scale=1))[0]
    assert out.x==pytest.approx(100+(8+10)*3) and out.y==pytest.approx(50+(72+10)*3) and out.width==pytest.approx(60)


def test_document_scroll_is_removed_before_viewport_mapping():
    ctx=geometry(scroll_x=200,scroll_y=300)
    assert transform_sensitive_rectangles([Rect(210,320,20,10,CoordinateSpace.BROWSER_DOCUMENT)],ctx)[0]==transform_sensitive_rectangles([Rect(10,20,20,10,CoordinateSpace.BROWSER_VIEWPORT)],ctx)[0]


def test_browser_chrome_offset_and_resized_window_are_explicit_inputs():
    ctx=geometry(content_offset_x=12,content_offset_y=96,browser_window_width=700,browser_window_height=500)
    out=transform_sensitive_rectangles([Rect(0,0,10,10,CoordinateSpace.BROWSER_VIEWPORT)],ctx)[0]
    assert out.x==pytest.approx(112) and out.y==pytest.approx(146) and ctx.browser_window_width==700


@pytest.mark.parametrize('monitor_x',[-1920,0,1920])
def test_physical_monitor_mapping_handles_negative_and_positive_monitor_origins(monitor_x):
    out=transform_sensitive_rectangles([Rect(5,7,20,30,CoordinateSpace.PHYSICAL_MONITOR)],geometry(monitor_x=monitor_x,screenshot_origin_x=monitor_x))[0]
    assert (out.x,out.y)==(5,7)


def test_virtual_desktop_mapping_handles_negative_origin_multi_monitor_layout():
    out=transform_sensitive_rectangles([Rect(100,50,25,25,CoordinateSpace.VIRTUAL_DESKTOP)],geometry(virtual_origin_x=-1920,virtual_origin_y=-200,screenshot_origin_x=-1920,screenshot_origin_y=-200))[0]
    assert (out.x,out.y)==(100,50)


def test_partially_offscreen_and_cross_monitor_rectangles_are_clipped():
    out=transform_sensitive_rectangles([Rect(-10,90,30,20,CoordinateSpace.SCREENSHOT_IMAGE)],geometry(screenshot_width=100,screenshot_height=100))[0]
    assert (out.x,out.y,out.width,out.height)==(0,90,20,10)


def test_malformed_or_fully_out_of_bounds_rectangle_fails_closed():
    assert clip_rect(Rect(float('nan'),0,10,10,CoordinateSpace.SCREENSHOT_IMAGE),100,100) is None
    with pytest.raises(GeometryError): transform_sensitive_rectangles([Rect(200,200,10,10,CoordinateSpace.SCREENSHOT_IMAGE)],geometry(screenshot_width=100,screenshot_height=100))


def test_missing_or_unsupported_geometry_fails_closed():
    with pytest.raises(GeometryError): transform_sensitive_rectangles([Rect(1,1,5,5,CoordinateSpace.BROWSER_VIEWPORT)],GeometryContext(screenshot_width=100,screenshot_height=100,screenshot_origin_x=0,screenshot_origin_y=0))


class FakeMSS:
    monitors=[{'width':40,'height':20,'left':-40,'top':0},{'width':20,'height':20,'left':-20,'top':0},{'width':20,'height':20,'left':0,'top':0}]
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def grab(self,mon): return SimpleNamespace(size=(int(mon['width']),int(mon['height'])),rgb=b'\xff'*(int(mon['width'])*int(mon['height'])*3))


def install_fake_mss(monkeypatch): monkeypatch.setitem(sys.modules,'mss',SimpleNamespace(mss=lambda:FakeMSS()))


def test_full_frame_fail_safe_redaction_writes_only_black_sanitized_image(tmp_path,monkeypatch):
    install_fake_mss(monkeypatch); rec=ScreenUnderstanding(None,tmp_path).observe_record(monitor=1,redactions=None)
    assert rec['redaction_status']=='full_frame_redacted' and rec['visual_evidence_unavailable'] is True
    with Image.open(tmp_path/rec['screenshot_evidence_ref']) as image: assert set(image.convert('RGB').getdata())=={(0,0,0)}


def test_typed_desktop_redaction_is_applied_before_persistence(tmp_path,monkeypatch):
    install_fake_mss(monkeypatch); rec=ScreenUnderstanding(None,tmp_path).observe_record(monitor=2,redactions=[{'x':0,'y':0,'width':5,'height':5,'space':'screenshot_image'}])
    assert rec['redaction_status']=='sanitized'
    with Image.open(tmp_path/rec['screenshot_evidence_ref']) as image: assert image.getpixel((1,1))==(0,0,0) and image.getpixel((10,10))==(255,255,255)


def test_no_unredacted_model_call_when_geometry_is_unknown(tmp_path,monkeypatch):
    install_fake_mss(monkeypatch); calls=[]; model=SimpleNamespace(vision=lambda prompt,image:calls.append((prompt,image)) or 'bad')
    result=ScreenUnderstanding(model,tmp_path).analyze(redactions=None); assert result['visual_evidence_unavailable'] is True and calls==[]


def png_bytes(value=(10,20,30)):
    image=Image.new('RGB',(12,8),value); buf=io.BytesIO(); image.save(buf,format='PNG'); return buf.getvalue()


def guarded_record(raw,**overrides):
    base={'redaction_status':'sanitized','visual_evidence_unavailable':False,'coordinate_space_version':COORDINATE_SPACE_VERSION,'expires_at':time.time()+60,'owner_id':'owner','device_id':'device','session_id':'session','sanitized_checksum':hashlib.sha256(raw).hexdigest(),'_sanitized_png':raw}; base.update(overrides); return base


def test_guard_rejects_unsanitized_unknown_expired_mismatched_and_tampered_evidence():
    raw=png_bytes(); guard=SanitizedEvidenceGuard()
    for patch in ({'redaction_status':'full_frame_redacted'},{'coordinate_space_version':999},{'expires_at':time.time()-1},{'owner_id':'other'},{'sanitized_checksum':'0'*64}):
        with pytest.raises(EvidenceGuardError): guard.consume(guarded_record(raw,**patch),owner_id='owner',device_id='device',session_id='session')


def test_guard_accepts_only_checksum_valid_sanitized_bound_evidence():
    raw=png_bytes(); assert SanitizedEvidenceGuard().consume(guarded_record(raw),owner_id='owner',device_id='device',session_id='session').startswith('data:image/png;base64,')


class FakeLocator:
    def __init__(self,count): self._count=count
    def count(self): return self._count
class FakeFrame:
    def __init__(self,count=0,fail=False): self._count=count; self.fail=fail
    def locator(self,selector):
        if self.fail: raise RuntimeError('frame unavailable')
        return FakeLocator(self._count)
class FakeBrowserPage:
    def __init__(self,frames): self.frames=frames; self.mask_seen=None
    def evaluate(self,script): return {'device_pixel_ratio':2,'page_zoom':1.25,'viewport_width':800,'viewport_height':600,'scroll_x':5,'scroll_y':10,'browser_window_x':-100,'browser_window_y':20,'browser_window_width':900,'browser_window_height':700,'content_offset_x':8,'content_offset_y':72}
    def screenshot(self,**kwargs): self.mask_seen=kwargs.get('mask'); return png_bytes()


def browser_with_page(tmp_path,page):
    browser=PersistentBrowser(tmp_path/'profile'); browser.context=object(); browser.page=page; return browser


def test_browser_native_masking_includes_sensitive_fields_in_iframes(tmp_path):
    page=FakeBrowserPage([FakeFrame(1),FakeFrame(2)]); result=browser_with_page(tmp_path,page).capture_sanitized_screenshot()
    assert result['available'] is True and result['sensitive_count']==3 and result['redaction_method']=='browser_native_element_mask' and len(page.mask_seen)==2 and result['geometry']['device_pixel_ratio']==2


def test_browser_native_capture_fails_closed_when_iframe_geometry_is_unavailable(tmp_path):
    result=browser_with_page(tmp_path,FakeBrowserPage([FakeFrame(1),FakeFrame(fail=True)])).capture_sanitized_screenshot(); assert result['available'] is False and result['reason']=='unsupported_geometry' and result['bytes']==b''


def test_browser_native_source_is_persisted_only_after_marked_sanitized(tmp_path):
    raw=png_bytes((40,50,60)); rec=ScreenUnderstanding(None,tmp_path).observe_record(sanitized_source={'available':True,'redaction_status':'sanitized','redaction_method':'browser_native_element_mask','sensitive_count':1,'bytes':raw,'geometry':{'device_pixel_ratio':2},'capture_source':'browser_native'},evidence_binding={'owner_id':'owner','device_id':'device','session_id':'session'})
    assert rec['sanitized_checksum']==hashlib.sha256(raw).hexdigest() and rec['owner_id']=='owner' and rec['capture_source']=='browser_native' and (tmp_path/rec['screenshot_evidence_ref']).read_bytes()==raw


def test_failed_browser_native_source_never_reaches_model_and_desktop_falls_back_full_frame(tmp_path,monkeypatch):
    install_fake_mss(monkeypatch); calls=[]; model=SimpleNamespace(vision=lambda *args:calls.append(args)); result=ScreenUnderstanding(model,tmp_path).analyze(sanitized_source={'available':False,'reason':'unsupported_geometry','bytes':b''}); assert result['visual_evidence_unavailable'] is True and calls==[]


def test_concurrent_evidence_ids_do_not_collide(tmp_path,monkeypatch):
    import threading
    install_fake_mss(monkeypatch); screen=ScreenUnderstanding(None,tmp_path); refs=[]; errors=[]
    def capture():
        try: refs.append(screen.observe_record(redactions=[])['screenshot_evidence_ref'])
        except Exception as exc: errors.append(exc)
    threads=[threading.Thread(target=capture) for _ in range(8)]; [t.start() for t in threads]; [t.join() for t in threads]
    assert not errors and len(refs)==len(set(refs))==8


def test_evidence_retention_deletes_expired_files(tmp_path,monkeypatch):
    import os
    install_fake_mss(monkeypatch); screen=ScreenUnderstanding(None,tmp_path,retention_seconds=300,max_evidence_files=20); first=screen.observe_record(redactions=[]); path=tmp_path/first['screenshot_evidence_ref']; old=time.time()-1000; os.utime(path,(old,old)); screen.observe_record(redactions=[]); assert not path.exists()


def test_symlink_and_path_traversal_resistance(tmp_path,monkeypatch):
    install_fake_mss(monkeypatch); target=tmp_path/'elsewhere'; target.mkdir(); (tmp_path/'screenshots').symlink_to(target,target_is_directory=True)
    with pytest.raises(PermissionError): ScreenUnderstanding(None,tmp_path).observe_record(redactions=[])


def test_coordinate_space_version_is_persisted(tmp_path,monkeypatch):
    install_fake_mss(monkeypatch); assert ScreenUnderstanding(None,tmp_path).observe_record(redactions=[])['coordinate_space_version']==COORDINATE_SPACE_VERSION
