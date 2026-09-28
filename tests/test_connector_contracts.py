import pytest
from dataclasses import replace
from types import SimpleNamespace
from integrations.contracts import *
from tools.registry import ToolRegistry,Tool,Risk

def test_builtin_manifests_validate():
    for m in builtin_manifests(): assert m.validate() is m
@pytest.mark.parametrize('factory',[gmail_manifest,calendar_manifest,slack_manifest,home_assistant_manifest])
def test_manifest_operation_names_are_namespaced(factory):
    m=factory(); assert all(o.name.startswith(m.connector_id+'.') for o in m.operations)
def test_missing_operations_fails():
    with pytest.raises(ValueError): ConnectorManifest('x','X','p',1,'none').validate()
def test_incompatible_version_fails():
    with pytest.raises(ValueError): replace(gmail_manifest(),schema_version=2).validate()
def test_duplicate_connector_fails():
    r=ConnectorManifestRegistry();r.register(gmail_manifest())
    with pytest.raises(ValueError):r.register(gmail_manifest())
def test_duplicate_operation_fails():
    m=gmail_manifest(); bad=replace(m,operations=(m.operations[0],m.operations[0]))
    with pytest.raises(ValueError):bad.validate()
def test_operation_classification_conflict_fails():
    o=replace(gmail_manifest().operations[0],allowed_data_classifications=('secret',),prohibited_data_classifications=('secret',))
    with pytest.raises(ValueError):o.validate()
def test_gmail_delete_is_prohibited():
    o=gmail_manifest().operation('gmail.delete');assert o.prohibited and o.approval=='prohibited'
def test_gmail_send_requires_approval():
    assert gmail_manifest().operation('gmail.send').approval=='required'
def test_calendar_delete_high_risk_reauth():
    o=calendar_manifest().operation('calendar.delete');assert o.risk=='destructive' and o.requires_reauth
def test_tool_registry_stricter_minimum_risk_wins(tmp_path):
    s=SimpleNamespace(autonomy_mode='act',data_dir=tmp_path);r=ToolRegistry(s);t=Tool('x','x',lambda p:1,Risk.READ_ONLY,minimum_risk=Risk.DESTRUCTIVE);r.register(t);assert t.risk==Risk.DESTRUCTIVE
    assert not r.authorize(t).allowed
def test_prohibited_tool_fails_closed(tmp_path):
    r=ToolRegistry(SimpleNamespace(autonomy_mode='act',data_dir=tmp_path));t=Tool('x','x',lambda p:1,prohibited=True);r.register(t);d=r.authorize(t);assert not d.allowed and 'prohibited' in d.reason
def test_secret_data_prohibition(tmp_path):
    r=ToolRegistry(SimpleNamespace(autonomy_mode='act',data_dir=tmp_path));t=Tool('x','x',lambda p:1,prohibited_data_classifications=('secret',));r.register(t);assert not r.authorize(t,data_classification='secret').allowed
def test_nested_calendar_attendee_is_destination():
    p={'event':{'attendees':[{'email':'a@example.com'}]}};assert ToolRegistry.destination(p)=='a@example.com'
def test_emergency_stop_stricter_than_connector(tmp_path):
    r=ToolRegistry(SimpleNamespace(autonomy_mode='act',data_dir=tmp_path));t=Tool('x','x',lambda p:1);r.register(t);r.set_emergency_stop(True);assert not r.authorize(t).allowed
