from __future__ import annotations

from types import SimpleNamespace
import threading

import pytest

from agent.executor import AgentExecutor, ExecutionCancelled
from automation.engine import AutomationEngine
from capabilities.benchmark import CapabilityBenchmark, CapabilityLevel
from core.events import EventBus
from devices.continuity import ContinuityService
from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore
from proactive.engine import AttentionRelevanceEngine
from tools.registry import Risk, Tool, ToolRegistry
from vision.computer_intelligence import ComputerIntelligence
from voice.intelligence import AdaptiveVoiceActivity, SemanticEndpointDetector, VoiceProfile


class NoPlanModels:
    def chat(self, *args, **kwargs):
        return 'ok'


class EmptyPlanner:
    def plan(self, *args, **kwargs):
        return {'steps': []}


def test_p21_adaptive_voice_and_endpoint_behavior():
    profile = VoiceProfile(min_endpoint_ms=300, max_endpoint_ms=700, min_voice_threshold=.01, noise_multiplier=2.0)
    vad = AdaptiveVoiceActivity(profile, initial_noise=.002)
    for _ in range(20):
        assert not vad.observe(.003, speech_active=False)
    assert vad.threshold >= .01
    assert vad.observe(.04, speech_active=False)

    endpoint = SemanticEndpointDetector(profile)
    assert not endpoint.update(voice=True, block_seconds=.1, now=10.0)
    assert not endpoint.update(voice=True, block_seconds=.1, now=10.1)
    assert not endpoint.update(voice=False, block_seconds=.1, now=10.25)
    assert endpoint.update(voice=False, block_seconds=.1, now=10.5)


def test_p21_executor_honors_pre_dispatch_cancellation(tmp_path):
    settings = SimpleNamespace(autonomy_mode='act')
    tools = ToolRegistry(settings)
    memory = MemoryStore(tmp_path / 'memory.sqlite3')
    executor = AgentExecutor(models=NoPlanModels(), tools=tools, memory=memory, events=EventBus())
    executor.planner = EmptyPlanner()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ExecutionCancelled):
        executor.chat('do not execute', cancel_event=cancelled)


class FakeComputerModels:
    def json(self, *args, **kwargs):
        return {
            'summary': 'click the visible control',
            'steps': [
                {
                    'kind': 'click',
                    'params': {'x': 120, 'y': 80},
                    'reason': 'activate control',
                    'verify': 'the control has visibly changed state',
                }
            ],
        }


class FakeScreen:
    def analyze(self, question, monitor=1):
        if str(question).startswith('Verify'):
            return {'screenshot': 'after.png', 'analysis': 'VERIFIED control changed'}
        return {'screenshot': 'before.png', 'analysis': 'A button is visible at x=120 y=80'}


class FakeDesktop:
    def __init__(self):
        self.version = 0

    def snapshot(self):
        return {'x': 0, 'y': 0, 'screen_sha256': str(self.version)}

    def click(self, x=None, y=None, button='left'):
        self.version += 1
        return {'ok': True, 'x': x, 'y': y}

    def verify_change(self, before, after, kind):
        return before['screen_sha256'] != after['screen_sha256']

    def undo_descriptor(self, kind, before, params):
        return None

    def apply_undo(self, descriptor):
        return {'ok': True}


def test_p22_computer_runtime_observes_acts_and_verifies(tmp_path):
    computer = ComputerIntelligence(FakeComputerModels(), tmp_path, controller=FakeDesktop())
    computer.screen = FakeScreen()
    result = computer.execute('click the visible control')
    assert result['ok'] is True
    assert result['committed'] is True
    assert result['evidence'][0]['action_verified'] is True
    assert result['evidence'][0]['semantic_verify']['verified'] is True


def test_p23_proactive_engine_is_calm_and_budgeted(tmp_path):
    engine = AttentionRelevanceEngine(
        tmp_path / 'attention.sqlite3',
        interruptions_per_hour=1,
        default_cooldown_seconds=3600,
    )
    first = engine.consider(
        'calendar',
        {'id': 'meeting-1', 'kind': 'meeting', 'due_in_minutes': 10, 'urgency': .8, 'importance': .8, 'message': 'Meeting soon'},
        now_ts=10000,
    )
    assert first.action == 'notify' and not first.suppressed
    duplicate = engine.consider(
        'calendar',
        {'id': 'meeting-1', 'kind': 'meeting', 'due_in_minutes': 10, 'urgency': .8, 'importance': .8, 'message': 'Meeting soon'},
        now_ts=10010,
    )
    assert duplicate.suppressed
    second = engine.consider(
        'automation',
        {'id': 'failure-2', 'kind': 'failure', 'failed': True, 'urgency': .9, 'importance': .9},
        now_ts=10020,
    )
    assert second.suppressed


class WorkflowExecutor:
    def __init__(self):
        self.calls = []

    def chat(self, prompt, cancel_event=None):
        self.calls.append(prompt)
        return f'done:{prompt}'


def test_p24_workflow_runtime_executes_steps_and_records_history(tmp_path):
    events = EventBus()
    executor = WorkflowExecutor()
    engine = AutomationEngine(
        tmp_path / 'automation.sqlite3',
        executor=executor,
        events=events,
        context_provider=lambda: {'owner': 'user'},
        default_retries=0,
    )
    workflow_id = engine.create_workflow(
        'Invoice flow',
        {'type': 'manual'},
        [
            {'kind': 'set', 'key': 'client', 'value': 'ACME'},
            {'kind': 'prompt', 'prompt': 'Process {{client}} invoice', 'retries': 0, 'timeout_seconds': 5},
            {'kind': 'emit', 'event': 'invoice.completed', 'payload': {'ok': True}},
        ],
    )
    run_id = engine.run_workflow(workflow_id, background=False)
    row = engine.runs(workflow_id, 1)[0]
    assert row['id'] == run_id
    assert row['status'] == 'completed'
    assert executor.calls == ['Process ACME invoice']


def test_p24_event_trigger_matches_condition(tmp_path):
    executor = WorkflowExecutor()
    engine = AutomationEngine(tmp_path / 'automation.sqlite3', executor=executor, poll_seconds=.01)
    workflow_id = engine.create_workflow(
        'Changed site',
        {'type': 'event', 'event': 'site.changed', 'condition': {'path': 'event.changed', 'op': 'eq', 'value': True}},
        [{'kind': 'prompt', 'prompt': 'Summarize change', 'retries': 0, 'timeout_seconds': 5}],
    )
    assert engine.trigger('site.changed', {'changed': False}) == []
    matches = engine.trigger('site.changed', {'changed': True})
    assert len(matches) == 1
    # Background execution is allowed to finish asynchronously; the trigger itself is the contract under test.
    assert engine.workflow(workflow_id)['id'] == workflow_id


def test_p25_second_brain_supersedes_old_explicit_preference_and_preserves_history(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    brain = SecondBrain(store)
    old_id = brain.remember(
        MemoryCandidate('preference', 'meeting time', 'Prefers morning meetings', .95, source='explicit-user', importance=.8)
    )
    new_id = brain.remember(
        MemoryCandidate('preference', 'meeting time', 'Prefers afternoon meetings', .96, source='explicit-user', importance=.9)
    )
    old = store.get(old_id)
    new = store.get(new_id)
    assert old['valid_to'] is not None and old['superseded_by'] == new_id
    assert new['valid_to'] is None
    assert store.conflicts()[0]['resolution'] == 'superseded'
    context = brain.context('meeting time', 5)
    assert context[0]['id'] == new_id
    assert store.usage(new_id)
    temporal = brain.temporal('meeting')
    assert {row['id'] for row in temporal} >= {old_id, new_id}


def test_p26_cross_device_handoff_uses_one_thread(tmp_path):
    service = ContinuityService(tmp_path / 'continuity.sqlite3')
    thread_id = service.create_thread('Research', device_id='phone', context={'topic': 'battery research'})
    service.append(thread_id, device_id='phone', kind='user_message', payload={'text': 'Research solid state batteries'})
    bundle = service.handoff(thread_id, from_device='phone', to_device='desktop')
    assert bundle['thread']['id'] == thread_id
    assert service.active_for_device('desktop')['id'] == thread_id
    service.append(thread_id, device_id='desktop', kind='assistant_message', payload={'text': 'Continued on desktop'})
    synced = service.sync('phone')
    assert synced['thread']['id'] == thread_id
    assert any(event['payload'].get('text') == 'Continued on desktop' for event in synced['events'])


class FakeToolRegistry:
    def __init__(self):
        self.permissions = object()
        self.names = {
            'computer_observe', 'computer_execute', 'browser_goto', 'browser_verify',
            'read_file', 'create_docx',
        }

    def get(self, name):
        if name not in self.names:
            raise KeyError(name)
        return object()


def test_p27_benchmark_never_claims_superior_from_structure_alone(tmp_path):
    runtime = {
        'voice': SimpleNamespace(backend=SimpleNamespace(cancel_response=lambda: None)),
        'tools': FakeToolRegistry(),
        'second_brain': SimpleNamespace(temporal=lambda *a, **k: []),
        'proactive': object(),
        'automations': SimpleNamespace(create_workflow=lambda *a, **k: None, _recover_interrupted_runs=lambda: None),
        'device_registry': object(),
        'continuity': object(),
        'vault': object(),
        'backups': object(),
        'telemetry': object(),
        'memory': object(),
    }
    benchmark = CapabilityBenchmark(tmp_path / 'benchmark.sqlite3', runtime=runtime)
    results = benchmark.run_all()
    assert results['voice']['level'] == int(CapabilityLevel.FUNCTIONAL)
    assert max(item['level'] for item in results.values()) <= int(CapabilityLevel.FUNCTIONAL)
    assert set(benchmark.COMPETITIVE_TASKS) >= {'inspect_the_screen', 'continue_on_another_device', 'request_permission_correctly'}
