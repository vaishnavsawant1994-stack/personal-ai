from __future__ import annotations

import sys
import threading

from agent.durable_executor import DurableAgentExecutor
from automation.engine import AutomationEngine
from capabilities.benchmark import CapabilityBenchmark
from capabilities.dialogue_evaluation import ModelDialogueEvaluation
from capabilities.scenarios import CompetitiveScenarioSuite
from core.config import settings
from core.durable_approval_runtime import DurableApprovalTurnRuntime
from core.events import EventBus
from core.preferences import Preferences
from core.telemetry import Telemetry
from devices.continuity import ContinuityService
from devices.gateway import DeviceGateway
from devices.registry import DeviceRegistry
from future_intelligence.program import FutureIntelligenceProgram
from integrations.plugins import PluginManifestRegistry
from integrations.runtime import build_integrations
from knowledge.governance import KnowledgeAuthority
from knowledge.store import KnowledgeStore
from memory.governance import GovernedMemory
from memory.second_brain import SecondBrain
from memory.store import MemoryStore
from memory.vector_store import VectorStore
from models.governed_router import GovernedModelRouter
from notifications.apns import APNsProvider
from proactive.engine import AttentionRelevanceEngine
from qualification.program import P3QualificationProgram
from qualification.voice import VoiceQualificationRecorder
from recovery.backup import BackupService
from security.vault import SecretVault
from security.owner_access import OwnerAccessStore
from tools import benchmark as benchmark_tools
from tools.builtins import register_builtin_tools
from tools.registry import ToolRegistry
from voice.realtime import RealtimeVoiceSession
from voice.wake_phrase import WakePhraseGate


def build_runtime():
    events=EventBus(); telemetry=Telemetry(settings.data_dir/'telemetry.json'); preferences=Preferences(settings.data_dir/'preferences.json'); backups=BackupService(settings.data_dir)
    memory=MemoryStore(settings.data_dir/'assistant.sqlite3'); models=GovernedModelRouter(settings,events=events,audit=memory.audit); models.set_owner_privacy(str(preferences.get('model_privacy_mode',settings.model_privacy_mode))); vector=VectorStore(settings.data_dir/'vectors.sqlite3',lambda text:models.embed(text,sensitivity='sensitive')); memory_engine=SecondBrain(memory,models,vector); second_brain=GovernedMemory(memory_engine,settings.data_dir/'memory-candidates.sqlite3',events=events)
    knowledge_store=KnowledgeStore(settings.data_dir/'knowledge.sqlite3',settings.data_dir/'knowledge'/'objects'); knowledge=KnowledgeAuthority(knowledge_store,events=events); device_registry=DeviceRegistry(settings.data_dir/'devices.sqlite3'); owner_access=OwnerAccessStore(settings.data_dir/'owner-access.sqlite3'); device_gateway=DeviceGateway(device_registry,events); continuity=ContinuityService(settings.data_dir/'continuity.sqlite3',events=events,second_brain=second_brain)
    primary_thread=continuity.latest_thread()
    if primary_thread is None: primary_thread_id=continuity.create_thread('Primary Personal AI Context',device_id='desktop',context={'surface':'desktop','topic':'current work'})
    else: primary_thread_id=primary_thread['id']; continuity.set_active('desktop',primary_thread_id)
    proactive=AttentionRelevanceEngine(settings.data_dir/'proactive.sqlite3',events=events,second_brain=second_brain,enabled=settings.proactive_enabled,interruptions_per_hour=settings.proactive_interruptions_per_hour,default_cooldown_seconds=settings.proactive_default_cooldown_seconds)
    vault=SecretVault(settings.data_dir/'vault.json',settings.vault_password or None); integrations,adapters,oauth,oauth_providers=build_integrations(settings,vault); plugins=PluginManifestRegistry(settings.data_dir/'plugins'); plugins.load(); apns=APNsProvider(settings,device_registry,events); tools=ToolRegistry(settings); tools.set_autonomy_mode(str(preferences.get('autonomy_mode',settings.autonomy_mode)))
    agent_executor=DurableAgentExecutor(models=models,tools=tools,memory=memory,events=events,second_brain=second_brain,knowledge=knowledge,telemetry=telemetry); executor=DurableApprovalTurnRuntime(agent_executor,continuity,settings.data_dir/'turn-runtime.sqlite3',events=events)
    def context_provider():
        latest=continuity.latest_thread(); return {'devices':device_registry.list(),'integrations':integrations.list(),'memory_count':len(second_brain.graph().get('nodes',[])),'continuity':latest or {},'focus_mode':bool(preferences.get('focus_mode',False))}
    automations=AutomationEngine(settings.data_dir/'automations.sqlite3',executor=executor,events=events,context_provider=context_provider,default_timeout_seconds=settings.workflow_default_timeout_seconds,default_retries=settings.workflow_default_retries)
    capability_objects=register_builtin_tools(tools,memory,settings,models=models,automation_engine=automations,apns=apns,second_brain=second_brain,events=events,proactive_engine=proactive,continuity_service=continuity,integration_adapters=adapters)
    voice=RealtimeVoiceSession(models,executor,events); voice_qualification=VoiceQualificationRecorder(settings.data_dir/'voice-qualification.sqlite3',events=events); p3_qualification=P3QualificationProgram(settings.data_dir/'p3-qualification.sqlite3'); wake_phrase=WakePhraseGate(events,phrases=(str(preferences.get('wake_phrase','Hey Personal')),)); events.subscribe('voice.transcript',lambda event:wake_phrase.accept(event.get('text',''))); events.subscribe('state',lambda event:telemetry.increment(f"state.{event.get('state','unknown')}")); events.subscribe('voice.reply',lambda event:telemetry.increment('voice.replies'))
    runtime={'events':events,'runtime_state':events.runtime_state,'memory':memory,'models':models,'second_brain':second_brain,'knowledge':knowledge,'knowledge_store':knowledge_store,'vector_store':vector,'device_registry':device_registry,'owner_access':owner_access,'device_gateway':device_gateway,'continuity':continuity,'proactive':proactive,'tools':tools,'executor':executor,'turn_runtime':executor,'agent_executor':agent_executor,'automations':automations,'integrations':integrations,'integration_adapters':adapters,'oauth':oauth,'oauth_providers':oauth_providers,'plugins':plugins,'vault':vault,'voice':voice,'voice_qualification':voice_qualification,'p3_qualification':p3_qualification,'wake_phrase':wake_phrase,'apns':apns,'telemetry':telemetry,'preferences':preferences,'backups':backups,'computer':capability_objects.get('computer'),'primary_continuity_thread_id':primary_thread_id}; p3_qualification.runtime=runtime
    future=FutureIntelligenceProgram(settings.data_dir/'future-intelligence',runtime=runtime); runtime.update({'future_intelligence':future,'everyday_intelligence':future.everyday,'life_graph':future.life_graph,'personal_operations':future.operations,'world_understanding':future.world,'personal_ai_everywhere':future.everywhere,'hybrid_intelligence':future.hybrid,'advanced_autonomy':future.autonomy})
    if hasattr(executor,'attach_autonomy'): executor.attach_autonomy(future.autonomy)
    benchmark=CapabilityBenchmark(settings.data_dir/'capability-benchmark.sqlite3',runtime=runtime); model_evaluation=ModelDialogueEvaluation(settings.data_dir/'model-dialogue-evaluation.sqlite3',models,audit=memory.audit); scenarios=CompetitiveScenarioSuite(runtime,benchmark); runtime.update({'benchmark':benchmark,'model_evaluation':model_evaluation,'capability_scenarios':scenarios}); benchmark_tools.register(tools,benchmark,scenarios)
    def append_continuity(kind,text,device_id=None,conversation_id=None,event_id=None):
        # Canonical request-aware surfaces persist their own conversation events.
        # Legacy/unscoped emitters fall back to the active continuity thread here.
        if not text or conversation_id:return
        source_device=str(device_id or 'desktop')
        try:
            thread=continuity.active_for_device(source_device)
            if thread is None:thread=continuity.resume(source_device)['thread']
            continuity.append(thread['id'],device_id=source_device,kind=kind,payload={'text':str(text)},event_id=str(event_id) if event_id else None)
        except Exception:pass
    events.subscribe('conversation.user',lambda event:append_continuity('user_message',event.get('text'),event.get('device_id'),event.get('conversation_id'),event.get('event_id') or event.get('message_id'))); events.subscribe('conversation.assistant',lambda event:append_continuity('assistant_message',event.get('text'),event.get('device_id'),event.get('conversation_id'),event.get('event_id') or event.get('message_id'))); events.subscribe('proactive.ingest',lambda event:proactive.consider(str(event.get('source','unknown')),dict(event.get('payload') or {}),context={**context_provider(),**dict(event.get('context') or {})})); events.subscribe('automation.failed',lambda event:proactive.consider('automation',{'kind':'failure','id':event.get('automation_id'),'failed':True,'importance':.7,'message':f"An automation failed: {event.get('error','unknown error')}"},context=context_provider())); events.subscribe('workflow.failed',lambda event:proactive.consider('workflow',{'kind':'failure','id':event.get('run_id'),'failed':True,'importance':.75,'message':f"A workflow needs attention: {event.get('error','workflow failed')}"},context=context_provider())); events.subscribe('workflow.approval_required',lambda event:proactive.consider('workflow',{'kind':'approval','id':event.get('run_id'),'needs_approval':True,'urgency':.7,'importance':.8,'message':f"A workflow is waiting for your approval to use {event.get('tool','a tool')}."},context=context_provider())); return runtime


def start_server(runtime):
    if not settings.control_server_enabled:return
    from server.api import create_app
    import uvicorn
    app=create_app(runtime['executor'],settings,device_registry=runtime['device_registry'],device_gateway=runtime['device_gateway'],second_brain=runtime['second_brain'],automations=runtime['automations'],runtime=runtime); uvicorn.run(app,host=settings.control_server_host,port=settings.control_server_port,log_level='warning')


def main():
    from PyQt6.QtWidgets import QApplication
    from desktop.floating_presence import FloatingPresence
    # Keep the historical lazy MainWindow import contract for headless/cloud
    # qualification while Stage 5 selects its canonical semantic-state wrapper.
    from ui.main_window import MainWindow
    from ui.canonical_main_window import CanonicalMainWindow
    app=QApplication(sys.argv); app.setApplicationName('Personal AI'); runtime=build_runtime(); runtime['automations'].start()
    if settings.control_server_enabled:threading.Thread(target=start_server,args=(runtime,),daemon=True).start()
    window=CanonicalMainWindow(events=runtime['events'],executor=runtime['executor'],memory=runtime['memory'],runtime=runtime); window.show(); floating_presence=FloatingPresence(runtime=runtime); runtime['floating_presence']=floating_presence; floating_presence.show()
    if runtime['preferences'].get('launch_voice_on_start'):window.toggle_voice()
    code=app.exec(); floating_presence.close(); runtime['voice'].stop(); runtime['automations'].stop(); runtime['telemetry'].persist(); runtime['apns'].close(); return code


if __name__=='__main__':raise SystemExit(main())
