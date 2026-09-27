from __future__ import annotations

import sys
import threading

from agent.executor import AgentExecutor
from automation.engine import AutomationEngine
from capabilities.benchmark import CapabilityBenchmark
from capabilities.scenarios import CompetitiveScenarioSuite
from core.config import settings
from core.events import EventBus
from core.preferences import Preferences
from core.telemetry import Telemetry
from devices.continuity import ContinuityService
from devices.gateway import DeviceGateway
from devices.registry import DeviceRegistry
from integrations.plugins import PluginManifestRegistry
from integrations.runtime import build_integrations
from memory.second_brain import SecondBrain
from memory.store import MemoryStore
from memory.vector_store import VectorStore
from models.router import ModelRouter
from notifications.apns import APNsProvider
from proactive.engine import AttentionRelevanceEngine
from qualification.program import P3QualificationProgram
from qualification.voice import VoiceQualificationRecorder
from recovery.backup import BackupService
from security.vault import SecretVault
from tools import benchmark as benchmark_tools
from tools.builtins import register_builtin_tools
from tools.registry import ToolRegistry
from voice.realtime import RealtimeVoiceSession
from voice.wake_phrase import WakePhraseGate


def build_runtime():
    events = EventBus()
    telemetry = Telemetry(settings.data_dir / 'telemetry.json')
    preferences = Preferences(settings.data_dir / 'preferences.json')
    backups = BackupService(settings.data_dir)
    memory = MemoryStore(settings.data_dir / 'assistant.sqlite3')
    models = ModelRouter(settings)
    vector = VectorStore(settings.data_dir / 'vectors.sqlite3', models.embed)
    second_brain = SecondBrain(memory, models, vector)

    device_registry = DeviceRegistry(settings.data_dir / 'devices.sqlite3')
    device_gateway = DeviceGateway(device_registry, events)
    continuity = ContinuityService(
        settings.data_dir / 'continuity.sqlite3',
        events=events,
        second_brain=second_brain,
    )
    primary_thread = continuity.latest_thread()
    if primary_thread is None:
        primary_thread_id = continuity.create_thread(
            'Primary Personal AI Context',
            device_id='desktop',
            context={'surface': 'desktop', 'topic': 'current work'},
        )
    else:
        primary_thread_id = primary_thread['id']
        continuity.set_active('desktop', primary_thread_id)

    proactive = AttentionRelevanceEngine(
        settings.data_dir / 'proactive.sqlite3',
        events=events,
        second_brain=second_brain,
        enabled=settings.proactive_enabled,
        interruptions_per_hour=settings.proactive_interruptions_per_hour,
        default_cooldown_seconds=settings.proactive_default_cooldown_seconds,
    )

    vault = SecretVault(settings.data_dir / 'vault.json', settings.vault_password or None)
    integrations, adapters, oauth, oauth_providers = build_integrations(settings, vault)
    plugins = PluginManifestRegistry(settings.data_dir / 'plugins')
    plugins.load()
    apns = APNsProvider(settings, device_registry, events)

    tools = ToolRegistry(settings)
    tools.set_autonomy_mode(str(preferences.get('autonomy_mode', settings.autonomy_mode)))
    executor = AgentExecutor(
        models=models,
        tools=tools,
        memory=memory,
        events=events,
        second_brain=second_brain,
        telemetry=telemetry,
    )

    def context_provider():
        latest = continuity.latest_thread()
        return {
            'devices': device_registry.list(),
            'integrations': integrations.list(),
            'memory_count': len(second_brain.graph().get('nodes', [])),
            'continuity': latest or {},
            'focus_mode': bool(preferences.get('focus_mode', False)),
        }

    automations = AutomationEngine(
        settings.data_dir / 'automations.sqlite3',
        executor=executor,
        events=events,
        context_provider=context_provider,
        default_timeout_seconds=settings.workflow_default_timeout_seconds,
        default_retries=settings.workflow_default_retries,
    )
    capability_objects = register_builtin_tools(
        tools,
        memory,
        settings,
        models=models,
        automation_engine=automations,
        apns=apns,
        second_brain=second_brain,
        events=events,
        proactive_engine=proactive,
        continuity_service=continuity,
    )

    voice = RealtimeVoiceSession(models, executor, events)
    voice_qualification = VoiceQualificationRecorder(
        settings.data_dir / 'voice-qualification.sqlite3',
        events=events,
    )
    p3_qualification = P3QualificationProgram(
        settings.data_dir / 'p3-qualification.sqlite3',
    )
    wake_phrase = WakePhraseGate(
        events,
        phrases=(str(preferences.get('wake_phrase', 'Hey Personal')),),
    )
    events.subscribe('voice.transcript', lambda event: wake_phrase.accept(event.get('text', '')))
    events.subscribe('state', lambda event: telemetry.increment(f"state.{event.get('state', 'unknown')}"))
    events.subscribe('voice.reply', lambda event: telemetry.increment('voice.replies'))

    runtime = {
        'events': events,
        'memory': memory,
        'models': models,
        'second_brain': second_brain,
        'vector_store': vector,
        'device_registry': device_registry,
        'device_gateway': device_gateway,
        'continuity': continuity,
        'proactive': proactive,
        'tools': tools,
        'executor': executor,
        'automations': automations,
        'integrations': integrations,
        'integration_adapters': adapters,
        'oauth': oauth,
        'oauth_providers': oauth_providers,
        'plugins': plugins,
        'vault': vault,
        'voice': voice,
        'voice_qualification': voice_qualification,
        'p3_qualification': p3_qualification,
        'wake_phrase': wake_phrase,
        'apns': apns,
        'telemetry': telemetry,
        'preferences': preferences,
        'backups': backups,
        'computer': capability_objects.get('computer'),
        'primary_continuity_thread_id': primary_thread_id,
    }
    p3_qualification.runtime = runtime
    benchmark = CapabilityBenchmark(settings.data_dir / 'capability-benchmark.sqlite3', runtime=runtime)
    scenarios = CompetitiveScenarioSuite(runtime, benchmark)
    runtime['benchmark'] = benchmark
    runtime['capability_scenarios'] = scenarios
    benchmark_tools.register(tools, benchmark, scenarios)

    def append_continuity(kind, text, device_id=None):
        if not text:
            return
        source_device = str(device_id or 'desktop')
        try:
            thread = continuity.active_for_device(source_device)
            if thread is None:
                bundle = continuity.resume(source_device)
                thread = bundle['thread']
            continuity.append(
                thread['id'],
                device_id=source_device,
                kind=kind,
                payload={'text': str(text)},
            )
        except Exception:
            pass

    events.subscribe(
        'conversation.user',
        lambda event: append_continuity('user_message', event.get('text'), event.get('device_id')),
    )
    events.subscribe(
        'conversation.assistant',
        lambda event: append_continuity('assistant_message', event.get('text'), event.get('device_id')),
    )

    events.subscribe(
        'proactive.ingest',
        lambda event: proactive.consider(
            str(event.get('source', 'unknown')),
            dict(event.get('payload') or {}),
            context={**context_provider(), **dict(event.get('context') or {})},
        ),
    )
    events.subscribe(
        'automation.failed',
        lambda event: proactive.consider(
            'automation',
            {
                'kind': 'failure',
                'id': event.get('automation_id'),
                'failed': True,
                'importance': 0.7,
                'message': f"An automation failed: {event.get('error', 'unknown error')}",
            },
            context=context_provider(),
        ),
    )
    events.subscribe(
        'workflow.failed',
        lambda event: proactive.consider(
            'workflow',
            {
                'kind': 'failure',
                'id': event.get('run_id'),
                'failed': True,
                'importance': 0.75,
                'message': f"A workflow needs attention: {event.get('error', 'workflow failed')}",
            },
            context=context_provider(),
        ),
    )
    events.subscribe(
        'workflow.approval_required',
        lambda event: proactive.consider(
            'workflow',
            {
                'kind': 'approval',
                'id': event.get('run_id'),
                'needs_approval': True,
                'urgency': 0.7,
                'importance': 0.8,
                'message': f"A workflow is waiting for your approval to use {event.get('tool', 'a tool')}.",
            },
            context=context_provider(),
        ),
    )
    return runtime


def start_server(runtime):
    if not settings.control_server_enabled:
        return
    from server.api import create_app
    import uvicorn

    app = create_app(
        runtime['executor'],
        settings,
        device_registry=runtime['device_registry'],
        device_gateway=runtime['device_gateway'],
        second_brain=runtime['second_brain'],
        automations=runtime['automations'],
        runtime=runtime,
    )
    uvicorn.run(
        app,
        host=settings.control_server_host,
        port=settings.control_server_port,
        log_level='warning',
    )


def main():
    from PyQt6.QtWidgets import QApplication
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName('Personal AI')
    runtime = build_runtime()
    runtime['automations'].start()
    if settings.control_server_enabled:
        threading.Thread(target=start_server, args=(runtime,), daemon=True).start()
    window = MainWindow(
        events=runtime['events'],
        executor=runtime['executor'],
        memory=runtime['memory'],
        runtime=runtime,
    )
    window.show()
    if runtime['preferences'].get('launch_voice_on_start'):
        window.toggle_voice()
    code = app.exec()
    runtime['voice'].stop()
    runtime['automations'].stop()
    runtime['telemetry'].persist()
    runtime['apns'].close()
    return code


if __name__ == '__main__':
    raise SystemExit(main())
