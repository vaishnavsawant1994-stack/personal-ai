import inspect
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from browser.observation import MAX_DOM_CHARS, MAX_VISIBLE_TEXT, find_target, normalized_url, observe_page, safe_browser_evidence, target_for_coordinates
from desktop.application_context import ApplicationContext, ApplicationContextObserver
from desktop.observation_policy import ObservationSafetyError, build_observation_record, canonical_digest, verify_material_context
from desktop.operator_transactions import OperatorBinding, OperatorTransactionStore
from security.approvals import ApprovalManager
from vision.screen_understanding import ScreenUnderstanding


BINDING = OperatorBinding('owner','device-1','session-1',11,'conversation-1','workflow-1')


class FakeLocator:
    def __init__(self, page): self.page=page
    def inner_text(self, timeout=5000): return self.page.visible
    def aria_snapshot(self, timeout=5000): return self.page.accessibility


class FakeContext:
    def __init__(self): self.pages=[]


class FakeFrame:
    def __init__(self,url): self.url=url


class FakeMSS:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    @property
    def monitors(self): return [{'width':20,'height':20,'left':0,'top':0},{'width':20,'height':20,'left':0,'top':0}]
    def grab(self, mon):
        return SimpleNamespace(size=(20,20), rgb=b"\xff" * (20*20*3))


def install_fake_mss(monkeypatch):
    monkeypatch.setitem(sys.modules,'mss',SimpleNamespace(mss=lambda:FakeMSS()))


class FakePage:
    def __init__(self):
        self.url='https://Example.com:443/account?token=TOPSECRET#frag'; self.visible='hello'; self.accessibility='button "Pay"'; self.context=FakeContext(); self.context.pages=[self]
        self.frames=[FakeFrame(self.url)]; self.dom='<html>'+('x'*(MAX_DOM_CHARS+200))+'</html>'
        self.elements=[{'index':0,'tag':'button','role':'button','type':'','name':'pay','label':'Pay','text':'Pay','placeholder':'','path':'html>body>button:nth-of-type(1)','sensitive':False,'visible':True,'topmost':True,'disabled':False,'box':{'x':10,'y':10,'width':100,'height':40}}, {'index':1,'tag':'input','role':'','type':'password','name':'','label':'[REDACTED]','text':'[REDACTED]','placeholder':'[REDACTED]','path':'','sensitive':True,'visible':True,'topmost':True,'disabled':False,'box':{'x':10,'y':80,'width':160,'height':30}}]
    def title(self): return 'Account'
    def locator(self, sel): return FakeLocator(self)
    def evaluate(self, script, arg=None):
        if 'activeElement' in script: return 0
        if 'cloneNode' in script: return self.dom
        return self.elements


def browser_snapshot():
    return {
        'captured_at':time.time(),'browser':'chromium','browser_context_id':'browser-1','tab_id':'tab-1','tab_index':0,'tab_count':1,
        'origin':'https://example.com','normalized_url':'https://example.com/account','domain':'example.com','visible_text_sha256':'v','dom_sha256':'d',
        'accessibility_sha256':'a','accessibility_available':True,'actionable_digest':'actions','frame_origins_digest':'frames','active_target_id':'target-1',
        'sensitive_regions':[],'elements':[{'target_id':'target-1','geometry_digest':'geo-1','actionable':True,'sensitive':False,'box':{'x':0,'y':0,'width':100,'height':100}}],
    }


def app_context(window='hwnd:1', app='chrome'):
    return {'available':True,'identity_digest':f'app-{app}','application':app,'executable':f'{app}.exe','process_id':10,'process_start_token':'start','window_id':window,'window_title_sha256':'title'}


def screen_record(obs='obs-1', *, ttl=120):
    now=time.time(); return {'observation_id':obs,'captured_at':now,'expires_at':now+ttl,'screenshot_evidence_ref':f'screenshots/{obs}.png','screen_fingerprint':f'screen-{obs}','redaction_count':0}


def durable(obs='obs-1', *, browser=True, ttl=120, window='hwnd:1'):
    return build_observation_record(binding=BINDING,transaction_id='tx-1',application=app_context(window),screen=screen_record(obs,ttl=ttl),browser=browser_snapshot() if browser else None,reason='test',initiator='authenticated_transaction')


def test_url_identity_strips_query_fragment_userinfo_and_default_port():
    value=normalized_url('https://user:pw@EXAMPLE.com:443/a?token=secret#x')
    assert value['origin']=='https://example.com' and value['normalized_url']=='https://example.com/a'
    assert 'secret' not in str(value) and 'user' not in str(value)


def test_browser_observation_has_stable_tab_origin_and_bounded_content():
    page=FakePage(); page.visible='z'*(MAX_VISIBLE_TEXT+100); snap=observe_page(page)
    assert snap['tab_id'].startswith('tab-') and snap['browser_context_id'].startswith('browser-')
    assert snap['origin']=='https://example.com' and '?' not in snap['normalized_url']
    assert len(snap['visible_text'])==MAX_VISIBLE_TEXT and len(snap['dom'])==MAX_DOM_CHARS


def test_browser_observation_redacts_password_and_exposes_only_redaction_region():
    snap=observe_page(FakePage()); secret=[x for x in snap['elements'] if x['sensitive']][0]
    assert secret['text']=='[REDACTED]' and secret['placeholder']=='[REDACTED]' and secret['name']==''
    assert snap['sensitive_region_count']==1 and snap['sensitive_regions'][0]['y']==80


def test_safe_browser_evidence_never_persists_raw_dom_text_or_elements():
    snap=observe_page(FakePage()); safe=safe_browser_evidence(snap)
    assert not {'dom','visible_text','accessibility','elements','sensitive_regions'}.intersection(safe)
    assert safe['dom_sha256'] and safe['accessibility_sha256'] and safe['actionable_digest']


def test_actionable_target_identity_and_geometry_are_stable():
    snap=observe_page(FakePage()); target=target_for_coordinates(snap,20,20)
    assert target and target['target_id']==find_target(snap,target['target_id'])['target_id']
    assert target['geometry_digest']


def test_unsupported_platform_fallback_never_fabricates_application(monkeypatch):
    monkeypatch.setattr('desktop.application_context.platform.system',lambda:'Linux')
    value=ApplicationContextObserver().capture()
    assert value['available'] is False and value['application']=='' and value['identity_digest']==''
    assert value['source']=='unsupported_platform'


def test_windows_foreground_capture_routes_to_verified_identity(monkeypatch):
    observer=ApplicationContextObserver(); expected=ApplicationContext(time.time(),'windows',True,'chrome','C:/Chrome/chrome.exe',42,'start','hwnd:abc','Title','win32_foreground_window')
    monkeypatch.setattr('desktop.application_context.platform.system',lambda:'Windows'); monkeypatch.setattr(observer,'_windows',lambda:expected)
    value=observer.capture()
    assert value['available'] is True and value['application']=='chrome' and value['executable']=='chrome.exe' and value['window_id']=='hwnd:abc' and value['identity_digest']
    assert 'window_title' not in value and value['window_title_sha256']


def test_observation_ids_and_screenshot_evidence_are_unique(tmp_path, monkeypatch):
    install_fake_mss(monkeypatch)
    s=ScreenUnderstanding(None,tmp_path); a=s.observe_record(); b=s.observe_record()
    assert a['observation_id']!=b['observation_id'] and a['screenshot_evidence_ref']!=b['screenshot_evidence_ref']
    assert (tmp_path/a['screenshot_evidence_ref']).exists() and (tmp_path/b['screenshot_evidence_ref']).exists()


def test_screenshot_redaction_occurs_before_checksum_and_persistence(tmp_path, monkeypatch):
    from PIL import Image
    install_fake_mss(monkeypatch)
    s=ScreenUnderstanding(None,tmp_path); rec=s.observe_record(redactions=[{'x':0,'y':0,'width':10,'height':10}])
    assert rec['redaction_count']==1
    with Image.open(tmp_path/rec['screenshot_evidence_ref']) as im: assert im.getpixel((2,2))==(0,0,0)


def test_symlink_evidence_directory_is_rejected(tmp_path, monkeypatch):
    target=tmp_path/'target'; target.mkdir(); (tmp_path/'screenshots').symlink_to(target,target_is_directory=True)
    install_fake_mss(monkeypatch)
    with pytest.raises(PermissionError,match='symlink'): ScreenUnderstanding(None,tmp_path).observe_record()


def test_observation_record_contains_required_binding_and_digest():
    record=durable()
    for key in ('observation_id','owner_id','device_id','session_id','security_epoch','transaction_id','application_identity','process_identity','window_identity','browser_tab_identity','browser_origin','normalized_url','captured_at','expires_at','screenshot_evidence_ref','screen_fingerprint','sanitized_dom_digest','accessibility_tree_digest','actionable_element_digest','sensitivity','capture_reason','capture_initiator','observation_digest'):
        assert key in record
    copy=dict(record); digest=copy.pop('observation_digest'); assert digest==canonical_digest(copy)


def test_application_unavailable_fails_closed():
    with pytest.raises(ObservationSafetyError) as exc:
        build_observation_record(binding=BINDING,transaction_id='tx',application={'available':False},screen=screen_record(),browser=None,reason='x',initiator='x')
    assert exc.value.code=='application_unavailable'


def test_durable_store_rejects_raw_observation_payloads(tmp_path):
    store=OperatorTransactionStore(tmp_path/'operator.sqlite3'); record=durable(); record['visible_text']='secret'
    with pytest.raises(ValueError,match='raw or secret'): store.save_observation(record)


def test_durable_observation_survives_restart(tmp_path):
    path=tmp_path/'operator.sqlite3'; store=OperatorTransactionStore(path); record=durable(); store.save_observation(record)
    reopened=OperatorTransactionStore(path); again=reopened.observation(record['observation_id'])
    assert again['observation_digest']==record['observation_digest'] and again['browser_origin']=='https://example.com'


def test_migration_is_additive_and_restart_safe(tmp_path):
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as con:
        con.executescript('''
        CREATE TABLE operator_transactions(transaction_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,device_id TEXT NOT NULL,session_id TEXT NOT NULL,security_epoch INTEGER NOT NULL,conversation_id TEXT NOT NULL DEFAULT '',workflow_id TEXT NOT NULL DEFAULT '',goal TEXT NOT NULL,goal_hash TEXT NOT NULL,plan_json TEXT NOT NULL,plan_hash TEXT NOT NULL,state TEXT NOT NULL,checkpoint_index INTEGER NOT NULL DEFAULT -1,cancel_requested INTEGER NOT NULL DEFAULT 0,deadline_at REAL,error_code TEXT NOT NULL DEFAULT '',recovery_reason TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,updated_at REAL NOT NULL,completed_at REAL);
        CREATE TABLE operator_actions(action_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,sequence INTEGER NOT NULL,kind TEXT NOT NULL,parameter_hash TEXT NOT NULL,expected_postcondition TEXT NOT NULL DEFAULT '',state TEXT NOT NULL,verified INTEGER NOT NULL DEFAULT 0,evidence_json TEXT NOT NULL DEFAULT '{}',error_code TEXT NOT NULL DEFAULT '',started_at REAL NOT NULL,completed_at REAL,UNIQUE(transaction_id,sequence));
        CREATE TABLE operator_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,transaction_id TEXT NOT NULL,action_id TEXT,event TEXT NOT NULL,payload_json TEXT NOT NULL,created_at REAL NOT NULL);
        ''')
    OperatorTransactionStore(path); OperatorTransactionStore(path)
    with sqlite3.connect(path) as con:
        cols={row[1] for row in con.execute('PRAGMA table_info(operator_actions)')}
        assert {'before_observation_id','after_observation_id','target_identity','plan_digest','observation_digest'}<=cols
        assert con.execute('PRAGMA user_version').fetchone()[0]==72
        assert con.execute("SELECT name FROM sqlite_master WHERE name='operator_observations'").fetchone()


def test_observation_expiry_rejects_dispatch_context():
    expected=durable(ttl=-1); current=durable('obs-2')
    with pytest.raises(ObservationSafetyError) as exc: verify_material_context(expected=expected,current=current,target_binding={'mode':'browser_element','target_id':'target-1','geometry_digest':'geo-1'},current_browser=browser_snapshot(),data_root=Path('.'))
    assert exc.value.code=='observation_expired'


@pytest.mark.parametrize('field,value',[
    ('application_identity','other-app'),('process_identity','other-process'),('window_identity','hwnd:2'),
    ('browser_context_identity','browser-2'),('browser_tab_identity','tab-2'),('browser_origin','https://evil.example'),('normalized_url','https://example.com/other'),('frame_origins_digest','other-frames'),
])
def test_material_context_changes_fail_closed(field,value):
    expected=durable(); current=dict(expected); current['observation_id']='obs-2'; current[field]=value
    with pytest.raises(ObservationSafetyError) as exc: verify_material_context(expected=expected,current=current,target_binding={'mode':'browser_element','target_id':'target-1','geometry_digest':'geo-1'},current_browser=browser_snapshot(),data_root=Path('.'))
    assert exc.value.code=='context_changed'


def test_changed_actionable_target_rejected():
    expected=durable(); current=durable('obs-2'); browser=browser_snapshot(); browser['elements']=[]
    with pytest.raises(ObservationSafetyError) as exc: verify_material_context(expected=expected,current=current,target_binding={'mode':'browser_element','target_id':'target-1','geometry_digest':'geo-1'},current_browser=browser,data_root=Path('.'))
    assert exc.value.code=='target_changed'


def test_target_geometry_change_rejected_but_unrelated_screen_fingerprint_change_allowed():
    expected=durable(); current=durable('obs-2'); current['screen_fingerprint']='animation-different'; browser=browser_snapshot()
    assert verify_material_context(expected=expected,current=current,target_binding={'mode':'browser_element','target_id':'target-1','geometry_digest':'geo-1'},current_browser=browser,data_root=Path('.'))
    browser['elements'][0]['geometry_digest']='moved'
    with pytest.raises(ObservationSafetyError) as exc: verify_material_context(expected=expected,current=current,target_binding={'mode':'browser_element','target_id':'target-1','geometry_digest':'geo-1'},current_browser=browser,data_root=Path('.'))
    assert exc.value.code=='target_changed'


def test_new_sensitive_region_rejects_dispatch():
    expected=durable(); current=durable('obs-2'); current['sensitivity']={'redaction_count':1,'sensitive_region_count':1}
    with pytest.raises(ObservationSafetyError) as exc: verify_material_context(expected=expected,current=current,target_binding={'mode':'browser_element','target_id':'target-1','geometry_digest':'geo-1'},current_browser=browser_snapshot(),data_root=Path('.'))
    assert exc.value.code=='target_changed'


def test_approval_hash_binds_plan_and_observation_digests(tmp_path):
    approvals=ApprovalManager(60,path=tmp_path/'approvals.sqlite3'); params={'goal':'x','_operator_plan_digest':'plan-a','_operator_observation_digest':'obs-a'}
    ticket=approvals.create('exec','computer_execute',params,owner_id='owner',device_id='device-1',session_id='session-1')
    changed=dict(params); changed['_operator_observation_digest']='obs-b'
    with pytest.raises(PermissionError,match='scope mismatch'): approvals.consume(ticket.id,'exec','computer_execute',changed,owner_id='owner',device_id='device-1',session_id='session-1')


def test_stale_approval_expires_without_dispatch(tmp_path):
    approvals=ApprovalManager(1,path=tmp_path/'approvals.sqlite3'); params={'_operator_plan_digest':'p','_operator_observation_digest':'o'}
    ticket=approvals.create('exec','computer_execute',params)
    with pytest.raises(PermissionError,match='expired'): approvals.consume(ticket.id,'exec','computer_execute',params,now=ticket.expires_at+0.01)


def test_action_rows_bind_before_after_target_plan_and_observation(tmp_path):
    store=OperatorTransactionStore(tmp_path/'operator.sqlite3'); plan={'steps':[{'kind':'click','params':{'x':1,'y':2}}]}; store.propose('tx',BINDING,goal='g',action_plan=plan); store.transition('tx','policy_check'); store.transition('tx','approval_required'); store.transition('tx','permitted'); store.transition('tx','executing')
    action,_=store.start_action('tx',1,kind='click',parameter_hash='params',expected_postcondition='done',before_observation_id='before',target_identity='target',plan_digest='plan',observation_digest='obs')
    store.finish_action(action['action_id'],verified=True,evidence={'before_sha256':'a','after_sha256':'b'},after_observation_id='after')
    row=store.actions('tx')[0]; assert row['before_observation_id']=='before' and row['after_observation_id']=='after' and row['target_identity']=='target' and row['plan_digest']=='plan' and row['observation_digest']=='obs'


def test_concurrent_action_start_creates_single_dispatch_checkpoint(tmp_path):
    store=OperatorTransactionStore(tmp_path/'operator.sqlite3'); plan={'steps':[{'kind':'click','params':{'x':1,'y':2}}]}; store.propose('tx',BINDING,goal='g',action_plan=plan); store.transition('tx','policy_check'); store.transition('tx','approval_required'); store.transition('tx','permitted'); store.transition('tx','executing')
    results=[]; errors=[]
    def work():
        try: results.append(store.start_action('tx',1,kind='click',parameter_hash='p',expected_postcondition='done',before_observation_id='before',target_identity='target',plan_digest='plan',observation_digest='obs')[1])
        except Exception as exc: errors.append(exc)
    threads=[threading.Thread(target=work) for _ in range(5)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert errors==[] and results.count(True)==1 and results.count(False)==4


def test_restart_recovery_preserves_observations_and_marks_uncertain_action(tmp_path):
    path=tmp_path/'operator.sqlite3'; store=OperatorTransactionStore(path); plan={'steps':[{'kind':'click','params':{'x':1,'y':2}}]}; store.propose('tx',BINDING,goal='g',action_plan=plan); store.transition('tx','policy_check'); store.transition('tx','approval_required'); store.transition('tx','permitted'); store.transition('tx','executing'); store.start_action('tx',1,kind='click',parameter_hash='p',expected_postcondition='done')
    rec=durable(); rec['transaction_id']='tx'; rec_no=dict(rec); rec_no.pop('observation_digest'); rec['observation_digest']=canonical_digest(rec_no); store.save_observation(rec)
    reopened=OperatorTransactionStore(path); assert reopened.transaction('tx')['state']=='recovery_review_required' and reopened.actions('tx')[0]['state']=='outcome_unknown' and reopened.observation(rec['observation_id'])


def test_capture_paths_have_no_background_monitoring_primitives():
    sources='\n'.join([inspect.getsource(ApplicationContextObserver.capture),inspect.getsource(ScreenUnderstanding.observe_record),inspect.getsource(observe_page)])
    lowered=sources.lower()
    assert 'thread(' not in lowered and 'timer(' not in lowered and 'while true' not in lowered and 'keyboard hook' not in lowered


def test_changed_production_files_contain_no_embedded_secret_patterns():
    import re
    root=Path(__file__).resolve().parents[1]
    files=[
        'browser/observation.py','browser/session.py','desktop/application_context.py',
        'desktop/observation_policy.py','desktop/operator_transactions.py','tools/advanced_control.py',
        'tools/computer.py','vision/computer_intelligence.py','vision/screen_understanding.py',
    ]
    patterns=[
        re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
        re.compile(r'\bsk-[A-Za-z0-9_-]{24,}\b'),
        re.compile(r'(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*=\s*["\'][^"\']{16,}["\']'),
    ]
    findings=[]
    for rel in files:
        text=(root/rel).read_text(encoding='utf-8')
        for pattern in patterns:
            if pattern.search(text): findings.append((rel,pattern.pattern))
    assert findings==[]
