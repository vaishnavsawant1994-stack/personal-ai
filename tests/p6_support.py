from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from agent.executor import AgentExecutor
from automation.engine import AutomationEngine
from core.events import EventBus
from future_intelligence.everyday import EverydayIntelligence
from future_intelligence.gates import TrustGate
from future_intelligence.operations import PersonalOperations
from memory.second_brain import SecondBrain
from memory.store import MemoryStore
from tools.registry import Risk, Tool, ToolRegistry


class FakeModels:
    """Deterministic local model facade; P6 must never use it to select a tool."""

    def __init__(self):
        self.chat_calls = 0
        self.plan_calls = 0

    def chat(self, *args, **kwargs):
        self.chat_calls += 1
        return 'deterministic delegated result'

    def json(self, *args, **kwargs):
        self.plan_calls += 1
        raise AssertionError('P6 exact delegation must not ask a model to select tools')


@dataclass
class Counter:
    value: int = 0


class Harness:
    def __init__(self, root: Path, *, mode='ask', qualified=True):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.settings = SimpleNamespace(data_dir=root, autonomy_mode=mode)
        self.events = EventBus()
        self.event_log = []
        self.memory = MemoryStore(root / 'assistant.sqlite3')
        self.second_brain = SecondBrain(self.memory)
        self.models = FakeModels()
        self.tools = ToolRegistry(self.settings)
        self.executor = AgentExecutor(
            models=self.models,
            tools=self.tools,
            memory=self.memory,
            events=self.events,
            second_brain=self.second_brain,
        )
        self.automations = AutomationEngine(
            root / 'automations.sqlite3',
            executor=self.executor,
            events=self.events,
            default_timeout_seconds=5,
            default_retries=0,
        )
        self.everyday = EverydayIntelligence(
            root / 'everyday.sqlite3',
            memory=self.memory,
            second_brain=self.second_brain,
            events=self.events,
        )
        self.gate = TrustGate()
        if qualified:
            self.gate.record_external_proof('p3.permissions', True, source='trusted-p6-harness')
            self.gate.record_external_proof('p3.automation', True, source='trusted-p6-harness')
        self.operations = PersonalOperations(
            gate=self.gate,
            executor=self.executor,
            automations=self.automations,
            events=self.events,
            second_brain=self.second_brain,
            memory=self.memory,
            everyday=self.everyday,
            path=root / 'future-intelligence' / 'operations.sqlite3',
        )
        for event in (
            'future.operation.planning', 'future.operation.queued', 'future.operation.executing',
            'future.operation.step_verified', 'future.operation.approval_required',
            'future.operation.waiting_reauth', 'future.operation.verifying',
            'future.operation.completed', 'future.operation.failed',
            'future.operation.cancelled', 'future.operation.recovery_required',
        ):
            self.events.subscribe(event, self.event_log.append)

    def close(self):
        self.automations.stop()

    def read_tool(self, name='read_context', *, handler=None, prohibited=False, requires_trusted_context=False):
        counter = Counter()

        def default_handler(params):
            counter.value += 1
            return {'value': params.get('value', 'ok')}

        self.tools.register(Tool(
            name,
            'deterministic read-only qualification tool',
            handler or default_handler,
            Risk.READ_ONLY,
            prohibited=prohibited,
            requires_trusted_context=requires_trusted_context,
        ))
        return counter

    def side_tool(
        self,
        name='send_action',
        *,
        handler=None,
        verifier=None,
        requires_reauth=False,
        verification_required=True,
        prohibited=False,
        risk=Risk.EXTERNAL_SIDE_EFFECT,
    ):
        counter = Counter()

        def default_handler(params):
            counter.value += 1
            return {'sent': True, 'reference': params.get('reference', 'simulated')}

        def default_verifier(params, result):
            return {
                'verified': bool(result and result.get('sent')),
                'reason': 'deterministic qualification verifier',
                'evidence': {'reference': str((result or {}).get('reference') or '')[:80]},
            }

        self.tools.register(Tool(
            name,
            'deterministic consequential qualification tool',
            handler or default_handler,
            risk,
            verifier=verifier or default_verifier,
            verification_required=verification_required,
            requires_reauth=requires_reauth,
            prohibited=prohibited,
        ))
        return counter

    @staticmethod
    def authority(**overrides):
        return {
            'owner_id': overrides.get('owner_id', 'owner'),
            'device_id': overrides.get('device_id', 'device-1'),
            'session_id': overrides.get('session_id', 'session-1'),
            **({'reauthenticated_at': overrides['reauthenticated_at']} if 'reauthenticated_at' in overrides else {}),
        }
