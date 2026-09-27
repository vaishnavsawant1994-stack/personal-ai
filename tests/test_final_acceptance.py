from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from agent.executor import AgentExecutor,ConfirmationRequired
from core.events import EventBus
from devices.registry import DeviceRegistry
from integrations.plugins import PluginManifestRegistry
from memory.store import MemoryStore
from security.approvals import ApprovalManager
from tools.registry import ToolRegistry,Tool,Risk
from tools import documents
from updates.signed_updater import SignedUpdater
from voice.wake_phrase import WakePhraseGate

class Models:
    def chat(self,*args,**kwargs):return 'completed'
class Planner:
    def __init__(self,plan):self.plan_value=plan;self.calls=0
    def plan(self,*args,**kwargs):self.calls+=1;return self.plan_value

def executor_for(tmp_path,plan,handler):
    settings=SimpleNamespace(autonomy_mode='ask');tools=ToolRegistry(settings);tools.register(Tool('dangerous','external action',handler,Risk.EXTERNAL_SIDE_EFFECT));memory=MemoryStore(tmp_path/'memory.sqlite3');ex=AgentExecutor(models=Models(),tools=tools,memory=memory,events=EventBus());ex.planner=Planner(plan);return ex

def test_exact_approval_resumes_without_replanning_and_is_one_use(tmp_path):
    calls=[];plan={'steps':[{'tool':'dangerous','parameters':{'value':7},'description':'change exact value'}]};ex=executor_for(tmp_path,plan,lambda p:calls.append(dict(p)) or {'ok':True})
    with pytest.raises(ConfirmationRequired) as info:ex.chat('do it')
    ticket=info.value.approval_id;assert ex.planner.calls==1 and calls==[]
    assert ex.approve(ticket)=='completed';assert calls==[{'value':7}] and ex.planner.calls==1
    with pytest.raises(PermissionError):ex.approve(ticket)

def test_approval_parameter_tampering_is_blocked(tmp_path):
    calls=[];plan={'steps':[{'tool':'dangerous','parameters':{'value':7}}]};ex=executor_for(tmp_path,plan,lambda p:calls.append(dict(p)))
    with pytest.raises(ConfirmationRequired) as info:ex.chat('do it')
    info.value.parameters['value']=999
    with pytest.raises(PermissionError):ex.approve(info.value.approval_id)
    assert calls==[]

def test_expired_approval_is_rejected():
    approvals=ApprovalManager(ttl_seconds=1);ticket=approvals.create('e1','tool',{'a':1})
    with pytest.raises(PermissionError):approvals.consume(ticket.id,'e1','tool',{'a':1},now=ticket.expires_at+1)

def test_device_revocation_immediately_blocks_authentication(tmp_path):
    registry=DeviceRegistry(tmp_path/'devices.sqlite3');device,bearer=registry.enroll('iPhone','ios');assert registry.authenticate(device['id'],bearer);assert registry.revoke(device['id']);assert not registry.authenticate(device['id'],bearer)

def test_memory_search_graph_and_audit_survive_reopen(tmp_path):
    path=tmp_path/'memory.sqlite3';store=MemoryStore(path);a=store.remember(type='preference',subject='coffee',content='oat milk',source='user',verified=True);b=store.remember(type='place',subject='cafe',content='near office');store.relate(a,'related_to',b);store.audit('acceptance','memory',{'ok':True});assert store.search('oat')[0]['id']==a;assert len(store.graph()['edges'])==1
    reopened=MemoryStore(path);assert any(x['id']==a for x in reopened.graph()['nodes']) and len(reopened.graph()['edges'])==1

def test_wake_phrase_opens_short_command_window():
    events=EventBus();seen=[];events.subscribe('voice.wake',lambda e:seen.append(e));gate=WakePhraseGate(events,window_seconds=5);first=gate.accept('Hey Personal, open my workspace',now=10);second=gate.accept('and show memory',now=12);third=gate.accept('do something',now=20);assert first['triggered'] and first['command']=='open my workspace';assert second['awake'] and second['command']=='and show memory';assert not third['awake'];assert seen[0]['phrase']=='hey personal'

def test_plugin_registry_rejects_insecure_remote_endpoint(tmp_path):
    root=tmp_path/'plugins';root.mkdir();(root/'bad.json').write_text('{"id":"bad","endpoint":"http://example.com"}',encoding='utf-8');registry=PluginManifestRegistry(root)
    with pytest.raises(ValueError):registry.load()
    (root/'bad.json').unlink();(root/'good.json').write_text('{"id":"good","name":"Good","endpoint":"https://example.com","permissions":["read"]}',encoding='utf-8');assert registry.load()[0].id=='good'

def test_document_outputs_are_confined_to_workspace(tmp_path):
    settings=SimpleNamespace(autonomy_mode='act',data_dir=tmp_path);registry=ToolRegistry(settings);documents.register(registry,settings);tool=registry.get('create_docx')
    with pytest.raises(ValueError):tool.handler({'path':str(tmp_path.parent/'escape.docx'),'paragraphs':['no']})
    result=tool.handler({'path':'reports/test.docx','title':'Personal AI','paragraphs':['ok']});assert Path(result['path']).exists();assert (tmp_path/'workspace') in Path(result['path']).parents

def test_signed_updater_can_restore_previous_installation(tmp_path):
    private=Ed25519PrivateKey.generate();public=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw);import base64
    install=tmp_path/'install';install.mkdir();(install/'old.txt').write_text('old');stage=tmp_path/'stage';stage.mkdir();(stage/'new.txt').write_text('new');updater=SignedUpdater(base64.b64encode(public).decode(),install);backup=updater.install_staged(stage);assert (install/'new.txt').read_text()=='new';updater.rollback(backup);assert (install/'old.txt').read_text()=='old' and not (install/'new.txt').exists()
