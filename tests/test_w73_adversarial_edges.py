import pytest
from security.policy_gateway import DecisionKind,PolicyGateway,PolicyOperation
from security.policy_targets import TargetValidationError,application_rule_matches,canonical_path,redirect_allowed


def test_http_https_redirects_require_explicit_final_origin_rule():
    https={'scheme':'https','host':'example.com','port':443}
    http={'scheme':'http','host':'example.com','port':80}
    assert redirect_allowed(http,'http://example.com/a','https://example.com/b')==(False,'redirect_not_allowed')
    assert redirect_allowed(http,'http://example.com/a','https://example.com/b',final_rule=https)==(True,'allow_explicit_cross_origin')
    assert redirect_allowed(https,'https://example.com/a','http://example.com/b')==(False,'redirect_not_allowed')
    assert redirect_allowed(https,'https://example.com/a','http://example.com/b',final_rule=http)==(True,'allow_explicit_cross_origin')


def test_cross_origin_redirect_requires_explicit_final_host_rule():
    source={'scheme':'https','host':'example.com','port':443}
    final={'scheme':'https','host':'login.example.net','port':443}
    assert redirect_allowed(source,'https://example.com','https://login.example.net')==(False,'redirect_not_allowed')
    assert redirect_allowed(source,'https://example.com','https://login.example.net',final_rule=final)==(True,'allow_explicit_cross_origin')


def test_reparse_and_mounted_paths_are_default_deny():
    root=r'C:\Owner\Safe'
    with pytest.raises(TargetValidationError):canonical_path(r'C:\Owner\Safe\file.txt',[root],path_is_reparse=True)
    with pytest.raises(TargetValidationError):canonical_path(r'C:\Owner\Safe\file.txt',[root],path_is_mounted=True)
    assert canonical_path(r'C:\Owner\Safe\file.txt',[root],path_is_mounted=True,allow_mounted=True).endswith('file.txt')


def test_gateway_requires_policy_opt_in_for_mounted_path(tmp_path):
    g=PolicyGateway(tmp_path/'p.db')
    g.add_policy(owner_id='owner',target_type='path',target_identity={'root':r'C:\Owner\Safe','allow_network':False,'allow_mounted':False},allowed_operations=['read'],security_epoch=1,reauthenticated=True)
    operation=PolicyOperation('read','owner','d','s',1,'path',{'path':r'C:\Owner\Safe\file.txt','approved_roots':[r'C:\Owner\Safe'],'path_is_mounted':True},destination=r'C:\Owner\Safe\file.txt')
    assert g.evaluate(operation).reason_code=='path_outside_allowed_root'
    p=g.store.list_policies('owner')[0]
    g.add_policy(policy_id=p['policy_id'],owner_id='owner',target_type='path',target_identity={'root':r'C:\Owner\Safe','allow_network':False,'allow_mounted':True},allowed_operations=['read'],security_epoch=1,reauthenticated=True)
    permitted=PolicyOperation('read','owner','d','s',1,'path',{'path':r'C:\Owner\Safe\file.txt','approved_roots':[r'C:\Owner\Safe'],'path_is_mounted':True,'allow_mounted':True},destination=r'C:\Owner\Safe\file.txt')
    assert g.evaluate(permitted).allowed


def test_application_name_spoofing_cannot_replace_identity():
    rule={'canonical_path':'/trusted/app','sha256':'abc','publisher':'Trusted Publisher','version':'1'}
    spoof={'canonical_path':'/evil/app','sha256':'def','publisher':'Trusted Publisher','version':'1','application_name':'Trusted App'}
    allowed,reason=application_rule_matches(rule,spoof)
    assert not allowed and reason=='application_not_allowed'


def test_destructive_delete_requires_reauth_then_explicit_approval(tmp_path):
    g=PolicyGateway(tmp_path/'d.db')
    g.add_policy(owner_id='owner',target_type='destination',target_identity={'identity':'file:1'},allowed_operations=['destructive_delete'],security_epoch=1,reauthenticated=True)
    operation=PolicyOperation('destructive_delete','owner','d','s',1,'destination',{'identity':'file:1'},destination='file:1')
    assert g.evaluate(operation).decision is DecisionKind.REAUTHENTICATION_REQUIRED
    assert g.evaluate(operation,reauthenticated=True).decision is DecisionKind.APPROVAL_REQUIRED
    assert g.evaluate(operation,reauthenticated=True,approved=True).decision is DecisionKind.ALLOW


def test_temp_file_confinement_uses_approved_root_not_prefix(tmp_path):
    g=PolicyGateway(tmp_path/'t.db');temp=tmp_path/'personal-ai-temp';temp.mkdir();evil=tmp_path/'personal-ai-temp-evil';evil.mkdir()
    g.add_policy(owner_id='owner',target_type='path',target_identity={'root':str(temp)},allowed_operations=['local_file_write'],security_epoch=1,reauthenticated=True)
    operation=PolicyOperation('local_file_write','owner','d','s',1,'path',{'path':str(evil/'x.tmp'),'approved_roots':[str(temp)]},destination=str(evil/'x.tmp'))
    assert g.evaluate(operation).reason_code=='path_outside_allowed_root'
