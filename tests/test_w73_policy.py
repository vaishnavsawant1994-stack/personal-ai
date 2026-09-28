import time
import pytest
from security.policy_gateway import DecisionKind, PolicyGateway, PolicyOperation


def op(**changes):
    values=dict(operation='read',owner_id='owner',device_id='d',session_id='s',security_epoch=1,target_type='destination',target_identity={'identity':'x'},destination='x',data_classification='public');values.update(changes);return PolicyOperation(**values)

def add(gateway,**changes):
    values=dict(owner_id='owner',target_type='destination',target_identity={'identity':'x'},allowed_operations=['read'],security_epoch=1,reauthenticated=True);values.update(changes);return gateway.add_policy(**values)

def test_default_deny_and_explicit_deny(tmp_path):
    g=PolicyGateway(tmp_path/'db.sqlite3');assert g.evaluate(op()).decision is DecisionKind.DENY;add(g,denied_operations=['read']);d=g.evaluate(op());assert d.decision is DecisionKind.DENY and d.reason_code=='explicit_policy_deny'

def test_expired_device_session_and_epoch_are_not_effective(tmp_path):
    g=PolicyGateway(tmp_path/'db.sqlite3');add(g,expires_at=time.time()-1);assert g.evaluate(op()).decision is DecisionKind.DENY;add(g,device_id='other');assert g.evaluate(op()).decision is DecisionKind.DENY;add(g,session_id='other');assert g.evaluate(op()).decision is DecisionKind.DENY;assert g.evaluate(op(security_epoch=2)).decision is DecisionKind.DENY

def test_emergency_stop_reauth_sensitive_and_secret(tmp_path):
    state={'stop':False};g=PolicyGateway(tmp_path/'db.sqlite3',emergency_stop=lambda:state['stop']);add(g,allowed_operations=['financial_transfer','external_upload']);state['stop']=True;assert g.evaluate(op(operation='financial_transfer')).reason_code=='emergency_stop_active';state['stop']=False;assert g.evaluate(op(operation='financial_transfer')).decision is DecisionKind.REAUTHENTICATION_REQUIRED;assert g.evaluate(op(operation='external_upload',data_classification='secret')).reason_code=='secret_transfer_blocked';assert g.evaluate(op(operation='external_upload',data_classification='sensitive')).decision is DecisionKind.APPROVAL_REQUIRED

def test_policy_change_invalidates_approval_and_one_action_permit(tmp_path):
    g=PolicyGateway(tmp_path/'db.sqlite3');p=add(g,approval_rule='always');operation=op();before=g.evaluate(operation);assert before.decision is DecisionKind.APPROVAL_REQUIRED;approved=g.evaluate(operation,approved=True,expected_policy_digest=before.policy_digest);assert approved.decision is DecisionKind.ALLOW;permit=g.issue_temporary_permit(operation,approved);assert g.consume_temporary_permit(permit['permit_id'],operation,approved);assert not g.consume_temporary_permit(permit['permit_id'],operation,approved);g.add_policy(policy_id=p['policy_id'],owner_id='owner',target_type='destination',target_identity={'identity':'x'},allowed_operations=['read'],security_epoch=1,reauthenticated=True);changed=g.evaluate(operation,approved=True,expected_policy_digest=approved.policy_digest);assert changed.reason_code=='policy_changed'

def test_unknown_outcome_requires_recovery_review(tmp_path):
    g=PolicyGateway(tmp_path/'db.sqlite3');add(g);d=g.evaluate(op(outcome_state='unknown'));assert d.decision is DecisionKind.RECOVERY_REVIEW_REQUIRED

def test_concurrent_policy_updates_increment_version(tmp_path):
    import threading
    g=PolicyGateway(tmp_path/'db.sqlite3');p=add(g);errors=[]
    def update():
        try:g.add_policy(policy_id=p['policy_id'],owner_id='owner',target_type='destination',target_identity={'identity':'x'},allowed_operations=['read'],security_epoch=1,reauthenticated=True)
        except Exception as exc:errors.append(exc)
    threads=[threading.Thread(target=update) for _ in range(5)];[t.start() for t in threads];[t.join() for t in threads];assert not errors;assert g.store.get(p['policy_id'])['version']==6

def test_restart_persistence_and_schema_73(tmp_path):
    path=tmp_path/'db.sqlite3';g=PolicyGateway(path);p=add(g);assert g.schema_version()==73;restarted=PolicyGateway(path);assert restarted.store.get(p['policy_id'])['active'] is True;assert restarted.schema_version()==73

def test_policy_change_requires_reauthentication(tmp_path):
    g=PolicyGateway(tmp_path/'db.sqlite3')
    with pytest.raises(PermissionError):g.add_policy(owner_id='owner',target_type='destination',target_identity={'identity':'x'},allowed_operations=['read'],security_epoch=1)

def test_migration_from_user_version_72_is_additive(tmp_path):
    import sqlite3
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as con:con.execute('CREATE TABLE legacy_w72_marker(id INTEGER PRIMARY KEY,value TEXT)');con.execute("INSERT INTO legacy_w72_marker(value) VALUES('keep')");con.execute('PRAGMA user_version=72')
    g=PolicyGateway(path);assert g.schema_version()==73
    with sqlite3.connect(path) as con:assert con.execute('SELECT value FROM legacy_w72_marker').fetchone()[0]=='keep';names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'operator_policies','operator_policy_permits','operator_policy_audit'}<=names

def test_repeated_initialization_keeps_schema_and_policy(tmp_path):
    path=tmp_path/'repeat.sqlite3';first=PolicyGateway(path);p=add(first)
    for _ in range(4):assert PolicyGateway(path).schema_version()==73
    assert PolicyGateway(path).store.get(p['policy_id'])['version']==1

def test_revocation_and_reset_restore_default_deny(tmp_path):
    g=PolicyGateway(tmp_path/'db.sqlite3');p=add(g);assert g.evaluate(op()).allowed;assert g.revoke_policy(p['policy_id'],owner_id='owner',reauthenticated=True);assert g.evaluate(op()).decision is DecisionKind.DENY;add(g);add(g,target_identity={'identity':'y'});assert g.reset_to_safe_defaults('owner',reauthenticated=True)>=2;assert g.evaluate(op()).decision is DecisionKind.DENY

def test_security_epoch_provider_invalidates_old_policy(tmp_path):
    state={'epoch':1};g=PolicyGateway(tmp_path/'db.sqlite3',security_epoch_provider=lambda:state['epoch']);add(g);assert g.evaluate(op()).allowed;state['epoch']=2;assert g.evaluate(op()).reason_code=='policy_changed'

def test_priority_cannot_override_explicit_deny(tmp_path):
    g=PolicyGateway(tmp_path/'db.sqlite3');add(g,priority=999);add(g,priority=1,denied_operations=['read']);assert g.evaluate(op()).reason_code=='explicit_policy_deny'

from security.policy_targets import TargetValidationError,application_rule_matches,canonical_path,classify_clipboard,domain_rule_matches,normalize_domain_rule,normalize_origin,redirect_allowed,validate_file_metadata

@pytest.mark.parametrize('bad',['https://user:pass@example.com','ftp://example.com'])
def test_url_credentials_and_scheme_blocked(bad):
    with pytest.raises(TargetValidationError):normalize_origin(bad)

def test_domain_confusion_scheme_port_and_subdomains():
    rule={'scheme':'https','host':'example.com','port':443,'include_subdomains':False};assert domain_rule_matches(rule,'https://example.com/a')[0];assert not domain_rule_matches(rule,'https://evil-example.com')[0];assert not domain_rule_matches(rule,'https://example.com.evil.test')[0];assert not domain_rule_matches(rule,'http://example.com')[0];assert not domain_rule_matches(rule,'https://example.com:8443')[0];sub={**rule,'include_subdomains':True};assert domain_rule_matches(sub,'https://sub.example.com')[0]

def test_idn_is_punycode_normalized():assert normalize_origin('https://bücher.example').host=='xn--bcher-kva.example'

def test_ip_private_network_restrictions():
    with pytest.raises(TargetValidationError):normalize_origin('https://127.0.0.1')
    with pytest.raises(TargetValidationError):normalize_origin('https://127.0.0.1',allow_ip_literal=True)
    assert normalize_origin('https://127.0.0.1',allow_ip_literal=True,allow_private_network=True).is_private_network

def test_unsafe_wildcard_rejected():
    with pytest.raises(TargetValidationError):normalize_domain_rule({'host':'*.example.com'})

def test_redirect_cross_origin_blocked():
    rule={'scheme':'https','host':'example.com'};assert redirect_allowed(rule,'https://example.com/a','https://example.com/b')[0];assert redirect_allowed(rule,'https://example.com','https://sub.example.com')[1]=='redirect_not_allowed'

def test_windows_traversal_unc_ads_reserved_and_case():
    root=r'C:\Users\Owner\Safe';good=canonical_path(r'c:\users\owner\safe\Report.txt',[root]);assert good.lower().endswith('report.txt')
    for bad in [r'C:\Users\Owner\Safe\..\secret.txt',r'\\server\share\x.txt',r'C:\Users\Owner\Safe\x.txt:secret',r'C:\Users\Owner\Safe\CON.txt']:
        with pytest.raises(TargetValidationError):canonical_path(bad,[root])

def test_posix_symlink_and_prefix_confusion(tmp_path):
    root=tmp_path/'safe';root.mkdir();outside=tmp_path/'safe-evil';outside.mkdir()
    with pytest.raises(TargetValidationError):canonical_path(str(outside/'x'),[str(root)])
    target=tmp_path/'target';target.mkdir();link=root/'link';link.symlink_to(target,target_is_directory=True)
    with pytest.raises(TargetValidationError):canonical_path(str(link/'x'),[str(root)])

def test_mime_signature_and_oversize(tmp_path):
    p=tmp_path/'x.pdf';p.write_bytes(b'not a pdf')
    with pytest.raises(TargetValidationError):validate_file_metadata(str(p),claimed_mime='application/pdf')
    p.write_bytes(b'%PDF-1.7\n'+b'x'*100);assert validate_file_metadata(str(p),claimed_mime='application/pdf',max_bytes=200)['mime']=='application/pdf'
    with pytest.raises(TargetValidationError):validate_file_metadata(str(p),max_bytes=10)

def test_clipboard_secret_detection_and_size():
    meta=classify_clipboard('password = supersecretvalue');assert meta['secret'] and meta['classification']=='secret'
    with pytest.raises(TargetValidationError):classify_clipboard('x'*100,max_bytes=10)

def test_http_https_never_confused():
    rule={'scheme':'https','host':'example.com','port':443};assert domain_rule_matches(rule,'https://example.com')[0];assert not domain_rule_matches(rule,'http://example.com')[0]

def test_explicit_subdomain_does_not_allow_siblings():
    rule={'scheme':'https','host':'api.example.com','port':443,'include_subdomains':False};assert domain_rule_matches(rule,'https://api.example.com')[0];assert not domain_rule_matches(rule,'https://www.example.com')[0]

def test_application_hash_replacement_detected():
    rule={'canonical_path':'/x/app','sha256':'aaa','publisher':'P','version':'1'};assert application_rule_matches(rule,dict(rule))[0];ok,reason=application_rule_matches(rule,{**rule,'sha256':'bbb'});assert not ok and reason=='application_changed'

def policy(g,target_type,target,ops,**kwargs):return g.add_policy(owner_id='owner',target_type=target_type,target_identity=target,allowed_operations=ops,security_epoch=1,reauthenticated=True,**kwargs)

def test_never_store_durable_write_blocked(tmp_path):
    g=PolicyGateway(tmp_path/'x.db');policy(g,'destination',{'identity':'x'},['local_file_write']);operation=PolicyOperation('local_file_write','owner','d','s',1,'destination',{'identity':'x'},destination='x',data_classification='NEVER_STORE');assert g.evaluate(operation).reason_code=='never_store_blocked'

def test_clipboard_read_write_separate_and_race(tmp_path):
    import hashlib
    g=PolicyGateway(tmp_path/'x.db');policy(g,'clipboard',{'destination':'app:x'},['clipboard_read']);read=PolicyOperation('clipboard_read','owner','d','s',1,'clipboard',{'destination':'app:x'},destination='app:x',parameters={'clipboard_content':'hello'});assert g.evaluate(read).decision is DecisionKind.ALLOW;write=PolicyOperation('clipboard_write','owner','d','s',1,'clipboard',{'destination':'app:x'},destination='app:x',parameters={'clipboard_content':'hello'});assert g.evaluate(write).decision is DecisionKind.DENY;expected=hashlib.sha256(b'hello').hexdigest();assert g.evaluate(read,expected_clipboard_digest=expected).allowed;changed=PolicyOperation(**{**read.__dict__,'parameters':{'clipboard_content':'changed'}});assert g.evaluate(changed,expected_clipboard_digest=expected).reason_code=='clipboard_changed'

def test_application_and_domain_both_required(tmp_path):
    g=PolicyGateway(tmp_path/'x.db');app={'canonical_path':'/app/browser','sha256':'abc','publisher':'','version':'1'};policy(g,'domain',{'scheme':'https','host':'example.com','port':443},['form_submission']);operation=PolicyOperation('form_submission','owner','d','s',1,'domain',{'url':'https://example.com'},application=app,destination='https://example.com',data_classification='public');assert g.evaluate(operation).reason_code=='application_not_allowed';policy(g,'application',app,['control','form_submission']);assert g.evaluate(operation).allowed

def test_executable_replacement_denied(tmp_path):
    g=PolicyGateway(tmp_path/'x.db');app={'canonical_path':'/app/tool','sha256':'old','publisher':'P','version':'1'};policy(g,'application',app,['control']);changed={**app,'sha256':'new'};operation=PolicyOperation('control','owner','d','s',1,'application',changed,application=changed);assert g.evaluate(operation).decision is DecisionKind.DENY

def test_audit_never_contains_clipboard_content(tmp_path):
    g=PolicyGateway(tmp_path/'x.db');policy(g,'clipboard',{'destination':'x'},['clipboard_read']);operation=PolicyOperation('clipboard_read','owner','d','s',1,'clipboard',{'destination':'x'},destination='x',parameters={'clipboard_content':'password=supersecret'});g.evaluate(operation);assert all('supersecret' not in str(row) for row in g.store.recent_audit('owner'))

def test_sensitive_external_requires_approval_even_when_domain_allowed(tmp_path):
    g=PolicyGateway(tmp_path/'x.db');policy(g,'domain',{'scheme':'https','host':'example.com','port':443},['external_upload']);operation=PolicyOperation('external_upload','owner','d','s',1,'domain',{'url':'https://example.com'},destination='https://example.com',data_classification='sensitive');assert g.evaluate(operation).decision is DecisionKind.APPROVAL_REQUIRED;assert g.evaluate(operation,approved=True).decision is DecisionKind.ALLOW

def test_high_risk_requires_reauth_then_strong_approval(tmp_path):
    g=PolicyGateway(tmp_path/'x.db');policy(g,'destination',{'identity':'merchant'},['purchase']);operation=PolicyOperation('purchase','owner','d','s',1,'destination',{'identity':'merchant'},destination='merchant');assert g.evaluate(operation).decision is DecisionKind.REAUTHENTICATION_REQUIRED;assert g.evaluate(operation,reauthenticated=True).decision is DecisionKind.APPROVAL_REQUIRED;assert g.evaluate(operation,reauthenticated=True,approved=True).allowed

def test_policy_sensitivity_ceiling(tmp_path):
    g=PolicyGateway(tmp_path/'x.db');policy(g,'destination',{'identity':'x'},['share'],sensitivity_restrictions=['personal']);operation=PolicyOperation('share','owner','d','s',1,'destination',{'identity':'x'},destination='x',data_classification='sensitive');assert g.evaluate(operation).decision is DecisionKind.APPROVAL_REQUIRED

def test_clipboard_secret_is_not_in_audit_details(tmp_path):
    g=PolicyGateway(tmp_path/'x.db');policy(g,'clipboard',{'destination':'local'},['clipboard_read']);operation=PolicyOperation('clipboard_read','owner','d','s',1,'clipboard',{'destination':'local'},destination='local',parameters={'clipboard_content':'-----BEGIN PRIVATE KEY----- abc'});g.evaluate(operation);assert 'PRIVATE KEY' not in repr(g.store.recent_audit('owner'))
