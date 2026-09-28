from pathlib import Path
import hashlib
import inspect
import pytest

from desktop.input_clipboard import MemoryClipboardAdapter,ClipboardSnapshot,validate_hotkey
from desktop.operator_transactions import OperatorBinding,OperatorTransactionStore
from desktop.platform_adapter import WindowIdentity,UnsupportedDesktopAdapter,WindowsDesktopAdapter
from desktop.safe_desktop_operator import DesktopAction,SafeDesktopOperator
from security.policy_gateway import PolicyGateway
from security.policy_targets import TargetValidationError


class FakeContext:
    def __init__(self,window='hwnd:1',exe='app.exe',pid=10):self.window=window;self.exe=exe;self.pid=pid
    def capture(self):return {'available':True,'application':'app','executable':self.exe,'process_id':self.pid,'process_start_token':'p1','window_id':self.window,'identity_digest':'app-digest'}

class FakeDesktop:
    platform_name='windows'
    def __init__(self,exe):self.exe=str(exe);self.sha=hashlib.sha256(Path(exe).read_bytes()).hexdigest();self.window='hwnd:1';self.released=0;self.launched=0;self.inputs=[];self.controls={'control:1':{'window_id':'hwnd:1','visible':True,'enabled':True}}
    def application_identity(self,executable):
        p=str(Path(executable).resolve())
        if p!=str(Path(self.exe).resolve()):raise PermissionError('application_not_allowed')
        return {'canonical_path':p,'sha256':self.sha,'publisher':'','version':''}
    def launch(self,executable,args):self.launched+=1;return {'process_id':55,'application':self.application_identity(executable),'window':{'window_id':'hwnd:55'}}
    def foreground_window(self):return WindowIdentity(10,str(Path(self.exe).resolve()),self.sha,self.window,'title',True,True,True)
    def find_window_for_process(self,pid,timeout_seconds=3.0):return WindowIdentity(pid,str(Path(self.exe).resolve()),self.sha,f'hwnd:{pid}','title',False,True,True)
    def control_state(self,target_id):return self.controls.get(target_id)
    def focus_window(self,window_id):self.window=window_id;return True
    def window_action(self,window_id,action,**kwargs):return window_id==self.window
    def input_click(self,x,y,button='left'):self.inputs.append(('click',x,y))
    def input_type(self,text):self.inputs.append(('type',text))
    def input_select(self,target_id,option):self.inputs.append(('select',target_id,option))
    def input_hotkey(self,keys):self.inputs.append(('hotkey',keys))
    def input_scroll(self,amount):self.inputs.append(('scroll',amount))
    def release_input(self):self.released+=1
    def read_visible_text(self,window_id,max_chars=12000):return 'visible ui'[:max_chars]

def add_app_policy(policy,desktop,binding,ops):policy.add_policy(owner_id=binding.owner_id,target_type='application',target_identity=desktop.application_identity(desktop.exe),allowed_operations=list(ops),security_epoch=binding.security_epoch,reauthenticated=True)
def add_path_policy(policy,root,binding,ops):policy.add_policy(owner_id=binding.owner_id,target_type='path',target_identity={'root':str(root)},allowed_operations=list(ops),security_epoch=binding.security_epoch,reauthenticated=True)
def add_clipboard_policy(policy,binding,ops,destination='clipboard'):policy.add_policy(owner_id=binding.owner_id,target_type='clipboard',target_identity={'destination':destination},allowed_operations=list(ops),security_epoch=binding.security_epoch,reauthenticated=True)

@pytest.fixture
def env(tmp_path):
    exe=tmp_path/'app.exe';exe.write_bytes(b'app');binding=OperatorBinding('owner','device','session',73);policy=PolicyGateway(tmp_path/'policy.db');tx=OperatorTransactionStore(tmp_path/'tx.db');desktop=FakeDesktop(exe);cb=MemoryClipboardAdapter('hello');op=SafeDesktopOperator(policy,tx,binding,desktop=desktop,clipboard=cb,context=FakeContext(exe=str(exe)))
    return tmp_path,binding,policy,tx,desktop,cb,op

def test_unsupported_platform_fails_closed():
    with pytest.raises(RuntimeError,match='unsupported_platform'):UnsupportedDesktopAdapter().foreground_window()
def test_windows_launch_requires_absolute_executable():
    with pytest.raises(TargetValidationError):WindowsDesktopAdapter().application_identity('python.exe')
def test_windows_arguments_are_separate_and_newline_rejected():
    assert WindowsDesktopAdapter._validate_args(['--name','A B'])==['--name','A B']
    with pytest.raises(ValueError):WindowsDesktopAdapter._validate_args(['bad\narg'])
def test_windows_uia_control_identity_is_not_fabricated():assert WindowsDesktopAdapter().control_state('unknown') is None
def test_hotkey_allowlist_blocks_shell_launcher():
    assert validate_hotkey(['ctrl','c'])==('ctrl','c')
    with pytest.raises(PermissionError):validate_hotkey(['win','r'])
def test_clipboard_snapshot_never_contains_raw():assert 'private text' not in str(ClipboardSnapshot.from_value('private text',3).safe_dict())
def test_clipboard_secret_detection():assert ClipboardSnapshot.from_value('password=supersecret',1).secret

def test_default_deny_application(env):
    root,b,p,t,d,c,op=env;r=op.execute(DesktopAction('launch','tx',executable=str(d.exe)));assert r.status=='blocked_by_policy' and r.reason_code=='application_not_allowed'
def test_approved_launch_verified(env):
    root,b,p,t,d,c,op=env;add_app_policy(p,d,b,{'launch'});r=op.execute(DesktopAction('launch','tx-launch',executable=str(d.exe)));assert r.status=='verified' and d.launched==1
def test_executable_replacement_is_rejected(env):
    root,b,p,t,d,c,op=env;add_app_policy(p,d,b,{'launch'});Path(d.exe).write_bytes(b'changed');d.sha=hashlib.sha256(Path(d.exe).read_bytes()).hexdigest();r=op.execute(DesktopAction('launch','tx-replace',executable=str(d.exe)));assert r.status=='blocked_by_policy'
def test_identified_control_click_is_foreground_bound(env):
    root,b,p,t,d,c,op=env;add_app_policy(p,d,b,{'application_input'});a=DesktopAction('click','tx-click',window_id='hwnd:1',target_id='control:1',x=5,y=6,parameters={'executable':str(d.exe)});r=op.execute(a);assert r.status=='verified' and d.inputs[-1]==('click',5,6)
def test_type_requires_verified_control_identity(env):
    root,b,p,t,d,c,op=env;add_app_policy(p,d,b,{'application_input'});r=op.execute(DesktopAction('type','tx-type',window_id='hwnd:1',target_id='missing',text='hello',parameters={'executable':str(d.exe)}));assert r.status=='recovery_review_required' and not d.inputs
def test_select_identified_control(env):
    root,b,p,t,d,c,op=env;add_app_policy(p,d,b,{'application_input'});r=op.execute(DesktopAction('select','tx-select',window_id='hwnd:1',target_id='control:1',option='A',parameters={'executable':str(d.exe)}));assert r.status=='verified' and d.inputs[-1][0]=='select'
def test_coordinate_fallback_requires_w72_fresh_verifier(env):
    root,b,p,t,d,c,_=env;d.controls={};add_app_policy(p,d,b,{'application_input'});params={'executable':str(d.exe),'verified_visual_target_id':'visual:1','visual_target_digest':'g','visual_observation_digest':'o'};a=DesktopAction('click','tx-visual',window_id='hwnd:1',target_id='visual:1',x=7,y=8,parameters=params);op=SafeDesktopOperator(p,t,b,desktop=d,clipboard=c,context=FakeContext(exe=str(d.exe)),visual_verifier=lambda action:True);assert op.execute(a).status=='verified'
def test_coordinate_fallback_without_verifier_never_dispatches(env):
    root,b,p,t,d,c,op=env;d.controls={};add_app_policy(p,d,b,{'application_input'});params={'executable':str(d.exe),'verified_visual_target_id':'visual:1','visual_target_digest':'g','visual_observation_digest':'o'};r=op.execute(DesktopAction('click','tx-novis',window_id='hwnd:1',target_id='visual:1',x=7,y=8,parameters=params));assert r.status=='recovery_review_required' and not d.inputs
def test_window_change_rejected_before_input(env):
    root,b,p,t,d,c,op=env;add_app_policy(p,d,b,{'application_input'});d.window='hwnd:2';r=op.execute(DesktopAction('click','tx-window',window_id='hwnd:1',target_id='control:1',x=5,y=6,parameters={'executable':str(d.exe)}));assert r.status!='verified' and not d.inputs
def test_emergency_stop_blocks_input(env):
    root,b,p,t,d,c,_=env;add_app_policy(p,d,b,{'application_input'});op=SafeDesktopOperator(p,t,b,desktop=d,clipboard=c,context=FakeContext(exe=str(d.exe)),emergency_stop=lambda:True);r=op.execute(DesktopAction('click','tx-stop',window_id='hwnd:1',target_id='control:1',x=1,y=1,parameters={'executable':str(d.exe)}));assert r.reason_code=='emergency_stop_active' and not d.inputs
def test_cancel_releases_input(env):
    root,b,p,t,d,c,op=env;a=DesktopAction('click','tx-cancel',window_id='hwnd:1',target_id='control:1',x=1,y=1,parameters={'executable':str(d.exe)});op._ensure_tx(a);t.request_cancel(a.transaction_id);r=op.execute(a);assert r.status=='cancelled' and d.released>=1

def test_file_copy_requires_source_read_and_destination_write_policy(env):
    root,b,p,t,d,c,op=env;add_path_policy(p,root,b,{'local_file_write'});s=root/'s.txt';s.write_text('abc');r=op.execute(DesktopAction('copy','tx-copy-deny',path=str(s),destination=str(root/'d.txt'),roots=[str(root)]));assert r.status=='blocked_by_policy'
def test_file_copy_dual_policy_and_verification(env):
    root,b,p,t,d,c,op=env;add_path_policy(p,root,b,{'read','local_file_write'});s=root/'s.txt';s.write_text('abc');r=op.execute(DesktopAction('copy','tx-copy',path=str(s),destination=str(root/'d.txt'),roots=[str(root)]));assert r.status=='verified' and (root/'d.txt').read_text()=='abc'
def test_path_escape_rejected(env):
    root,b,p,t,d,c,op=env;r=op.execute(DesktopAction('file_metadata','tx-path',path=str(root/'..'/'x'),roots=[str(root)]));assert r.status=='blocked_by_policy' and r.reason_code=='path_not_allowed'
def test_bounded_text_read_returns_content_but_audit_redacts_it(env):
    root,b,p,t,d,c,op=env;add_path_policy(p,root,b,{'read'});f=root/'x.txt';f.write_text('approved text');r=op.execute(DesktopAction('read_file','tx-read',path=str(f),roots=[str(root)]));assert r.status=='verified' and r.result['text']=='approved text' and 'approved text' not in str(t.audit('tx-read'))
def test_binary_read_routes_away_from_model_text(env):
    root,b,p,t,d,c,op=env;add_path_policy(p,root,b,{'read'});f=root/'x.pdf';f.write_bytes(b'%PDF-1.4');r=op.execute(DesktopAction('read_file','tx-pdf',path=str(f),roots=[str(root)]));assert r.status=='verification_failed' and r.reason_code=='file_type_not_allowed'
def test_permanent_delete_requires_reauth_then_approval(env):
    root,b,p,t,d,c,op=env;add_path_policy(p,root,b,{'destructive_delete'});f=root/'x.txt';f.write_text('x');a=DesktopAction('permanent_delete','tx-del',path=str(f),roots=[str(root)],parameters={'rollback_claim':'irreversible'});assert op.execute(a).status=='reauthentication_required';assert op.execute(a,reauthenticated=True).status=='approval_required';r=op.execute(a,reauthenticated=True,approved=True);assert r.status=='verified' and r.rollback=='irreversible' and not f.exists()
def test_trash_requires_reauth_and_reports_compensating_action(env):
    root,b,p,t,d,c,op=env;add_path_policy(p,root,b,{'delete','local_file_write'});trash=root/'trash';trash.mkdir();f=root/'x.txt';f.write_text('x');a=DesktopAction('trash','tx-trash',path=str(f),trash_root=str(trash),roots=[str(root)]);assert op.execute(a).status=='reauthentication_required';r=op.execute(a,reauthenticated=True);assert r.status=='verified' and r.rollback=='compensating_action_available'

def test_clipboard_read_permission_and_redaction(env):
    root,b,p,t,d,c,op=env;assert op.execute(DesktopAction('clipboard_read','tx-cb1',parameters={'destination':'clipboard'})).status=='blocked_by_policy';add_clipboard_policy(p,b,{'clipboard_read'});r=op.execute(DesktopAction('clipboard_read','tx-cb2',parameters={'destination':'clipboard'}));assert r.status=='verified' and 'hello' not in str(r.result)
def test_clipboard_local_secret_write_never_audits_raw(env):
    root,b,p,t,d,c,op=env;add_clipboard_policy(p,b,{'clipboard_write'});r=op.execute(DesktopAction('clipboard_write','tx-cbw',text='password=supersecret',data_classification='secret',parameters={'destination':'clipboard'}));assert r.status=='verified' and 'supersecret' not in str(t.audit('tx-cbw'))
def test_secret_clipboard_external_transfer_blocked(env):
    root,b,p,t,d,c,op=env;add_clipboard_policy(p,b,{'clipboard_transfer'},'external-app');r=op.execute(DesktopAction('clipboard_write','tx-secret-xfer',text='password=supersecret',data_classification='secret',parameters={'destination':'external-app'}));assert r.status=='blocked_by_policy' and r.reason_code=='secret_transfer_blocked'
def test_clipboard_change_after_authorization_rejected(env,monkeypatch):
    root,b,p,t,d,c,op=env;add_clipboard_policy(p,b,{'clipboard_read'});original=op._capture;calls={'n':0}
    def changing(*args,**kwargs):
        calls['n']+=1
        if calls['n']==2:c.write_text('changed')
        return original(*args,**kwargs)
    monkeypatch.setattr(op,'_capture',changing);r=op.execute(DesktopAction('clipboard_read','tx-race',parameters={'destination':'clipboard'}));assert r.status=='blocked_by_policy' and r.reason_code=='clipboard_changed'

def test_restart_recovery_never_redispatches(env):
    root,b,p,t,d,c,op=env;add_app_policy(p,d,b,{'launch'});a=DesktopAction('launch','tx-restart',executable=str(d.exe));op._ensure_tx(a);t.transition(a.transaction_id,'permitted');t.transition(a.transaction_id,'executing');recovered=OperatorTransactionStore(root/'tx.db');op2=SafeDesktopOperator(p,recovered,b,desktop=d,clipboard=c,context=FakeContext(exe=str(d.exe)));before=d.launched;r=op2.execute(a);assert r.status=='recovery_review_required' and d.launched==before
def test_owner_device_session_mismatch_rejected(env):
    root,b,p,t,d,c,op=env;a=DesktopAction('launch','tx-bind',executable=str(d.exe));op._ensure_tx(a);other=SafeDesktopOperator(p,t,OperatorBinding('owner','other','session',73),desktop=d,clipboard=c,context=FakeContext(exe=str(d.exe)));assert other.execute(a).status=='blocked_by_policy'
def test_schema_73_reused(env):
    root,b,p,t,d,c,op=env;assert p.schema_version()==73
def test_no_shell_hooks_keylogging_or_background_monitoring():
    import desktop.platform_adapter as pa,desktop.safe_desktop_operator as sd
    source=(inspect.getsource(pa)+inspect.getsource(sd)).lower();assert 'shell=true' not in source and 'keyboard.hook' not in source and 'setinterval' not in source and 'keylog' not in source and 'powershell' not in source and 'cmd.exe' not in source
