import inspect
import pytest

from browser.safe_operator import BrowserAction, SafeBrowserOperator, STRONG_OWNER_ACTIONS, CHALLENGE_RE, sanitize_download_filename
from desktop.operator_transactions import OperatorBinding, OperatorTransactionStore
from security.policy_gateway import PolicyGateway


def _obs(**overrides):
    base={'browser_context_id':'ctx','tab_id':'tab','tab_count':1,'origin':'https://example.com','normalized_url':'https://example.com/','visible_text':'','elements':[],'dom_sha256':'d1','accessibility_sha256':'a1','actionable_digest':'x1','frame_origins_digest':'f1','active_target_id':'','sensitive_region_count':0}
    base.update(overrides); return base


def test_safe_download_filename_keeps_basename():
    assert sanitize_download_filename('report.pdf')=='report.pdf'

@pytest.mark.parametrize('name',['../secret.txt','..\\secret.txt','C:\\evil.txt','NUL.txt','CON',''])
def test_unsafe_download_names_rejected(name):
    with pytest.raises(ValueError): sanitize_download_filename(name)


def test_iframe_origin_change_is_postcondition_failure():
    op=object.__new__(SafeBrowserOperator)
    ok,reason=op._verify(BrowserAction('click','t',target_id='x'),_obs(frame_origins_digest='a'),_obs(frame_origins_digest='b'),{})
    assert not ok and reason=='iframe_origin_changed'


def test_post_action_tab_substitution_is_failure():
    op=object.__new__(SafeBrowserOperator)
    ok,reason=op._verify(BrowserAction('click','t',target_id='x'),_obs(tab_id='a'),_obs(tab_id='b'),{})
    assert not ok and reason=='tab_substitution'


def test_challenge_detector_covers_captcha_and_mfa():
    assert CHALLENGE_RE.search('Please verify you are human with CAPTCHA')
    assert CHALLENGE_RE.search('Enter your authenticator code for two-factor verification')


def test_strong_owner_actions_include_required_side_effects():
    required={'email_send','message_send','purchase','financial_transfer','public_publish','share','delete','security_setting_modify','permission_change','legal_acceptance'}
    assert required.issubset(STRONG_OWNER_ACTIONS)


def test_upload_requires_file_path():
    op=object.__new__(SafeBrowserOperator)
    with pytest.raises(ValueError): op._validate(BrowserAction('upload','t',target_id='x'))


def test_download_requires_confined_root():
    op=object.__new__(SafeBrowserOperator)
    with pytest.raises(ValueError): op._validate(BrowserAction('download','t',target_id='x'))


def test_observation_ids_are_unique(tmp_path):
    p=PolicyGateway(tmp_path/'p.db'); store=OperatorTransactionStore(tmp_path/'t.db'); binding=OperatorBinding('o','d','s',1)
    op=SafeBrowserOperator(object(),p,store,binding); op._observe=lambda:_obs()
    a=BrowserAction('open_url','tx',url='https://example.com/')
    first=op._capture(a,'one'); second=op._capture(a,'two')
    assert first['observation_id']!=second['observation_id']


def test_browser_operator_has_no_cookie_storage_or_background_monitoring_calls():
    source=inspect.getsource(SafeBrowserOperator).lower()
    assert 'cookies(' not in source
    assert 'local_storage' not in source and 'session_storage' not in source
    assert 'threading' not in source and 'setinterval' not in source


def test_navigation_verification_uses_normalized_origin_objects():
    op=object.__new__(SafeBrowserOperator)
    ok,reason=op._verify(BrowserAction('open_url','t',url='https://example.com/path'),_obs(),_obs(normalized_url='https://example.com/other'),{})
    assert ok and reason=='navigation_verified'


@pytest.mark.parametrize('url', [
    'file:///etc/passwd',
    'http://127.0.0.1/admin',
    'http://169.254.169.254/latest/meta-data/',
    'http://[::1]/',
    'https://user:password@example.com/',
])
def test_navigation_rejects_unsafe_or_private_targets_before_dispatch(url):
    op=object.__new__(SafeBrowserOperator)
    with pytest.raises(Exception):
        op._validate(BrowserAction('open_url','t',url=url))


def test_execute_reports_unsafe_navigation_as_denied_without_browser_dispatch():
    op=object.__new__(SafeBrowserOperator)
    op.browser=type('NeverBrowser',(),{'start':lambda self: (_ for _ in ()).throw(AssertionError('browser dispatch must not start'))})()
    r=op.execute(BrowserAction('open_url','tx-private',url='http://127.0.0.1/admin'))
    assert r.status=='denied' and r.reason_code=='destination_not_allowed'


def test_public_navigation_target_is_valid():
    op=object.__new__(SafeBrowserOperator)
    op._validate(BrowserAction('open_url','t',url='https://example.com/path'))


def test_https_downgrade_rejected_with_dataclass_origin_contract():
    op=object.__new__(SafeBrowserOperator)
    ok,reason=op._verify(BrowserAction('open_url','t',url='https://example.com/'),_obs(),_obs(origin='http://example.com',normalized_url='http://example.com/'),{})
    assert not ok and reason=='redirect_not_allowed'


def test_upload_dispatch_rejects_file_changed_after_authorization(tmp_path):
    path=tmp_path/'upload.txt'
    path.write_text('authorized',encoding='utf-8')
    op=object.__new__(SafeBrowserOperator)
    expected=op._file_digest(str(path))
    path.write_text('substituted',encoding='utf-8')
    action=BrowserAction('upload','tx-upload',target_id='file',upload_path=str(path),parameters={'_validated_upload_sha256':expected})
    fake_locator=type('Locator',(),{'set_input_files':lambda self,*args,**kwargs: (_ for _ in ()).throw(AssertionError('changed file must not be uploaded'))})()
    fake_page=object()
    op.browser=type('Browser',(),{'start':lambda self: None})()
    op.browser.page=fake_page
    op._target=lambda obs,target_id: {'target_id':target_id}
    op._resolve_target=lambda page,target,action: ('dom',fake_locator)
    with pytest.raises(PermissionError,match='changed after authorization'):
        op._dispatch(action,_obs())


def test_download_root_identity_changes_are_rejected(tmp_path):
    root=tmp_path/'downloads'
    root.mkdir()
    op=object.__new__(SafeBrowserOperator)
    authorized=op._download_root_identity(str(root))
    original=root.with_name('downloads-authorized')
    root.rename(original)
    root.mkdir()
    replacement=op._download_root_identity(str(root))
    assert replacement!=authorized
    action=BrowserAction('download','tx-download',target_id='download',download_root=str(root),parameters={'_validated_download_root_identity':authorized})
    class NeverDownloadPage:
        def expect_download(self,*args,**kwargs):
            raise AssertionError('download must not start after root substitution')
    op.browser=type('Browser',(),{'start':lambda self: None})()
    op.browser.page=NeverDownloadPage()
    op._target=lambda obs,target_id: {'target_id':target_id}
    op._resolve_target=lambda page,target,action: ('dom',object())
    with pytest.raises(PermissionError,match='download root changed after authorization'):
        op._dispatch(action,_obs())
