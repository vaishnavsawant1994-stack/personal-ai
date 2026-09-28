from pathlib import Path
import pytest
from future_intelligence.gates import TrustGate
from future_intelligence.everyday import EverydayIntelligence
from future_intelligence.deep_brain import LifeGraph
from future_intelligence.operations import PersonalOperations
from future_intelligence.multimodal import WorldUnderstanding
from future_intelligence.sovereignty import HybridIntelligenceRouter,ModelTarget
from future_intelligence.autonomy import AdvancedAutonomy
from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore


def test_p4_briefing_and_forgotten_commitments(tmp_path):
    p=EverydayIntelligence(tmp_path/'daily.sqlite3')
    p.add('goal','Ship Personal AI',priority=.9);p.add('commitment','Follow up tomorrow',priority=.8)
    b=p.briefing();assert b['counts']['open']==2;assert len(b['possible_forgotten_commitments'])==1


def test_p4_briefing_includes_authoritative_second_brain_context(tmp_path):
    store=MemoryStore(tmp_path/'memory.sqlite3');brain=SecondBrain(store)
    memory_id=brain.remember(MemoryCandidate(type='goal',subject='Release',content='Release Personal AI only after qualification.',confidence=.95,source='explicit-user',verified=True))
    p=EverydayIntelligence(tmp_path/'daily.sqlite3',second_brain=brain)
    briefing=p.briefing()
    assert memory_id in {row['id'] for row in briefing['relevant_memory']}


def test_p5_decision_requires_evidence_for_why(tmp_path):
    g=LifeGraph(tmp_path/'life.sqlite3');d=g.node('decision','Use iPhone first')
    empty=g.explain_decision(d);assert empty['answerable'] is False
    reason=g.node('event','No laptop available');g.relate(d,reason,'decided_because',rationale='physical constraint')
    assert g.explain_decision(d)['answerable'] is True


def test_p6_is_fail_closed_until_trust_is_proven():
    gate=TrustGate();ops=PersonalOperations(gate=gate);p=ops.create_plan('Research',[{'kind':'research','instruction':'collect sources'}])
    assert ops.execute(p['id'])['blocked'] is True
    gate.record_external_proof('p3.permissions',True,source='trusted-harness');gate.record_external_proof('p3.automation',True,source='trusted-harness')
    assert ops.execute(p['id'])['started'] is True


def test_consequential_p6_still_requires_approval():
    gate=TrustGate();gate.record_external_proof('p3.permissions',True,source='harness');gate.record_external_proof('p3.automation',True,source='harness')
    ops=PersonalOperations(gate=gate);p=ops.create_plan('Send',[{'kind':'send','instruction':'send document','consequential':True}])
    assert ops.execute(p['id'])['approval_required'] is True


def test_p7_records_source_attributed_observations_only():
    gate=TrustGate();w=WorldUnderstanding(gate=gate)
    with pytest.raises(ValueError):w.ingest('camera',{},source='')
    assert w.ingest('wearable',{'heart_rate':80},source='paired-device')['modality']=='wearable'


def test_p9_privacy_routing_is_gated_and_prefers_local():
    gate=TrustGate();r=HybridIntelligenceRouter(gate=gate);r.register(ModelTarget('cloud','cloud',False,('chat',),True,1));r.register(ModelTarget('local','local',True,('chat',),True,5))
    assert r.route(capability='chat')['blocked'] is True
    gate.record_external_proof('p3.permissions',True,source='harness');gate.record_external_proof('p3.reliability',True,source='harness')
    assert r.route(capability='chat',sensitivity='secret')['target']['id']=='local'


def test_p10_cannot_self_activate():
    gate=TrustGate();a=AdvancedAutonomy(gate=gate);agent=a.create_agent('Researcher','research',['web'])
    result=a.enable_agent(agent['id']);assert result['blocked'] is True
    with pytest.raises(ValueError):gate.record_external_proof('p3.reliability',True,source='model')


def test_p6_plan_survives_restart(tmp_path):
    gate=TrustGate();path=tmp_path/'operations.sqlite3';first=PersonalOperations(gate=gate,path=path)
    plan=first.create_plan('Persisted plan',[{'instruction':'resume safely'}])
    second=PersonalOperations(gate=gate,path=path)
    assert second.plan(plan['id'])['title']=='Persisted plan'


def test_p7_observation_survives_restart(tmp_path):
    gate=TrustGate();path=tmp_path/'world.sqlite3';first=WorldUnderstanding(gate=gate,path=path)
    item=first.ingest('document',{'name':'owner-note'},source='owner upload')
    second=WorldUnderstanding(gate=gate,path=path)
    assert second.recent()[0]['id']==item['id']


def test_p10_policy_outcome_and_emergency_stop_survive_restart(tmp_path):
    gate=TrustGate();path=tmp_path/'autonomy.sqlite3';first=AdvancedAutonomy(gate=gate,path=path)
    agent=first.create_agent('Researcher','Find evidence',['web']);first.set_policy(agent['id'],tool_allowlist=['web_search'],budget_limit=2)
    first.record_outcome('research','complete',success=True,evidence={'report':'retained'});first.emergency_stop()
    second=AdvancedAutonomy(gate=gate,path=path)
    assert second.status()['emergency_stop'] is True
    assert second.status()['agents'][0]['tool_allowlist']==['web_search']
    assert second.self_evaluation()['success_rate']==1
