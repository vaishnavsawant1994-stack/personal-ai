from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agent.executor import AgentExecutor, ConfirmationRequired, ReauthenticationRequired
from core.events import EventBus
from memory.store import MemoryStore
from tools.registry import Risk, Tool, ToolRegistry


class Models:
    def __init__(self):
        self.prompts = []

    def chat(self, prompt, *args, **kwargs):
        self.prompts.append(str(prompt))
        return 'reported'


class Planner:
    def __init__(self, plan):
        self.plan_value = plan

    def plan(self, *args, **kwargs):
        return self.plan_value


def executor(tmp_path, tool: Tool, plan: dict):
    settings = SimpleNamespace(autonomy_mode='ask', data_dir=tmp_path)
    registry = ToolRegistry(settings)
    registry.register(tool)
    models = Models()
    instance = AgentExecutor(
        models=models,
        tools=registry,
        memory=MemoryStore(tmp_path / 'assistant.sqlite3'),
        events=EventBus(),
    )
    instance.planner = Planner(plan)
    return instance, models


def test_side_effect_without_verifier_is_recorded_unverified(tmp_path):
    tool = Tool('send', 'send', lambda params: {'ok': True}, Risk.EXTERNAL_SIDE_EFFECT)
    plan = {'steps': [{'tool': 'send', 'parameters': {'recipient': 'person@example.com'}}]}
    ex, models = executor(tmp_path, tool, plan)

    with pytest.raises(ConfirmationRequired) as proposed:
        ex.chat('send it', device_id='device-1', session_id='session-1')
    assert ex.approve(proposed.value.approval_id, device_id='device-1', session_id='session-1') == 'reported'

    assert '"verified": false' in models.prompts[-1].lower()
    audit = ex.memory.audit_entries('tool', 5)[0]['payload']
    assert audit['verified'] is False
    assert 'params' not in audit
    assert ex.verify_action_audit()['ok'] is True


def test_custom_verifier_and_rollback_metadata_are_exposed(tmp_path):
    tool = Tool(
        'update',
        'update',
        lambda params: {'remote_id': 'r-1'},
        Risk.EXTERNAL_SIDE_EFFECT,
        verifier=lambda params, result: {
            'verified': result.get('remote_id') == 'r-1',
            'reason': 'remote object re-read matched',
            'evidence': {'remote_id': result.get('remote_id')},
        },
        rollback=lambda params, result: {'restored': True},
        rollback_description='restore previous remote value',
        verification_required=True,
    )
    plan = {'steps': [{'tool': 'update', 'parameters': {'recipient': 'person@example.com'}}]}
    ex, models = executor(tmp_path, tool, plan)

    with pytest.raises(ConfirmationRequired) as proposed:
        ex.chat('update it', device_id='device-1', session_id='session-1')
    ex.approve(proposed.value.approval_id, device_id='device-1', session_id='session-1')

    prompt = models.prompts[-1].lower()
    assert '"verified": true' in prompt
    assert '"available": true' in prompt
    assert 'restore previous remote value' in prompt


def test_secret_external_destination_requires_recent_reauthentication(tmp_path):
    tool = Tool('send', 'send', lambda params: {'verified': True}, Risk.EXTERNAL_SIDE_EFFECT)
    plan = {'steps': [{'tool': 'send', 'parameters': {'recipient': 'person@example.com'}}]}
    ex, _ = executor(tmp_path, tool, plan)
    ex.second_brain = SimpleNamespace(
        context=lambda *_: [{'sensitivity': 'secret', 'content': 'private'}],
        extract_candidates=lambda *_: [],
    )

    with pytest.raises(ReauthenticationRequired):
        ex.chat('send the secret', device_id='device-1', session_id='session-1')

    with pytest.raises(ConfirmationRequired):
        ex.chat(
            'send the secret',
            device_id='device-1',
            session_id='session-1',
            reauthenticated_at=time.time(),
        )


def test_destination_allowlist_is_hard_policy_not_approval_bypass(tmp_path):
    tool = Tool(
        'send',
        'send',
        lambda params: {'verified': True},
        Risk.EXTERNAL_SIDE_EFFECT,
        allowed_destinations=('example.com',),
    )
    plan = {'steps': [{'tool': 'send', 'parameters': {'recipient': 'person@evil.test'}}]}
    ex, _ = executor(tmp_path, tool, plan)

    with pytest.raises(PermissionError, match='allowlist'):
        ex.chat('send it', device_id='device-1', session_id='session-1')
