from __future__ import annotations

import ast
from collections import deque
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from agent.executor import AgentExecutor
from core.events import EventBus
from core.runtime_state import LEGAL_TRANSITIONS, RuntimeState
from core.turn_context import new_turn_context, reset_turn_context, set_turn_context
from desktop.floating_presence import PresenceController
from tools.registry import Risk, Tool, ToolRegistry


ROOT = Path(__file__).resolve().parents[1]
ALL_STATES = tuple(RuntimeState)
ALLOWED_EDGES = tuple(
    (source, target)
    for source in ALL_STATES
    for target in sorted(LEGAL_TRANSITIONS[source], key=lambda state: state.value)
)
ILLEGAL_EDGES = tuple(
    (source, target)
    for source in ALL_STATES
    for target in ALL_STATES
    if target != source and target not in LEGAL_TRANSITIONS[source]
)


def _route_from_idle(target: RuntimeState) -> list[RuntimeState]:
    if target is RuntimeState.IDLE:
        return []
    queue = deque([(RuntimeState.IDLE, [])])
    seen = {RuntimeState.IDLE}
    while queue:
        state, route = queue.popleft()
        for candidate in sorted(LEGAL_TRANSITIONS[state], key=lambda item: item.value):
            if candidate in seen:
                continue
            next_route = [*route, candidate]
            if candidate is target:
                return next_route
            seen.add(candidate)
            queue.append((candidate, next_route))
    raise AssertionError(f'{target.value} is not reachable from IDLE')


def _enter(runtime, state: RuntimeState):
    for step in _route_from_idle(state):
        runtime.transition(step, reason='graph-setup')
    assert runtime.state is state


@pytest.mark.parametrize(('source', 'target'), ALLOWED_EDGES)
def test_every_declared_legal_transition_executes_without_force(source, target):
    runtime = EventBus().runtime_state
    _enter(runtime, source)
    before = runtime.snapshot()
    after = runtime.transition(target, reason='legal-edge')
    assert after.state is target
    assert after.sequence == before.sequence + 1


@pytest.mark.parametrize(('source', 'target'), ILLEGAL_EDGES)
def test_every_undeclared_transition_fails_closed_without_partial_update(source, target):
    runtime = EventBus().runtime_state
    _enter(runtime, source)
    before = runtime.snapshot()
    with pytest.raises(ValueError):
        runtime.transition(target, reason='illegal-edge')
    assert runtime.snapshot() == before


def test_turn_completed_is_a_real_verified_terminal_success_producer():
    events = EventBus()
    seen = []
    events.subscribe('runtime.state', seen.append)
    events.emit('turn.started', request_id='r1')
    events.emit('state', state='thinking', request_id='r1')
    events.emit('state', state='speaking', request_id='r1')
    events.emit('turn.completed', request_id='r1')

    snapshot = events.runtime_state.snapshot()
    assert snapshot.request_id == 'r1'
    assert snapshot.state is RuntimeState.SUCCESS
    assert [item['state'] for item in seen][-2:] == ['RESPONDING', 'SUCCESS']


def test_turn_completed_cannot_invent_success_from_idle():
    events = EventBus()
    before = events.runtime_state.snapshot()
    events.emit('turn.completed', request_id='r1')
    assert events.runtime_state.snapshot() == before


def test_unverified_tool_outcome_finishes_as_warning_not_success():
    events = EventBus()
    events.emit('turn.started', request_id='r1')
    events.runtime_state.transition(RuntimeState.THINKING, reason='plan', request_id='r1')
    events.runtime_state.transition(RuntimeState.TOOL_ACTION, reason='dispatch', request_id='r1')
    events.emit('tool.unverified', request_id='r1', reason='verification unavailable')
    assert events.runtime_state.state is RuntimeState.WARNING
    # Production final response may communicate the degraded result, but completion
    # must restore WARNING rather than turn unverified work into SUCCESS.
    events.emit('state', state='speaking', request_id='r1')
    events.emit('turn.completed', request_id='r1')
    assert events.runtime_state.state is RuntimeState.WARNING


def test_duplicate_terminal_completion_is_idempotent():
    events = EventBus()
    events.emit('turn.started', request_id='r1')
    events.emit('state', state='speaking', request_id='r1')
    events.emit('turn.completed', request_id='r1')
    before = events.runtime_state.snapshot()
    events.emit('turn.completed', request_id='r1')
    assert events.runtime_state.snapshot() == before


def test_stale_r1_completion_cannot_move_r2_after_real_takeover():
    events = EventBus()
    events.emit('turn.started', request_id='r1')
    events.emit('state', state='speaking', request_id='r1')
    events.emit('turn.started', request_id='r2')
    before = events.runtime_state.snapshot()
    events.emit('turn.completed', request_id='r1')
    assert events.runtime_state.snapshot() == before
    assert before.request_id == 'r2'
    assert before.state is RuntimeState.UNDERSTANDING


def test_required_rapid_state_path_is_interruptible_and_latest_state_wins(tmp_path):
    events = EventBus()
    presence = PresenceController(events, tmp_path / 'presence.json')
    try:
        events.emit('turn.started', request_id='r1')
        for state in (
            RuntimeState.MEMORY_RETRIEVAL,
            RuntimeState.THINKING,
            RuntimeState.RESPONDING,
            RuntimeState.SUCCESS,
        ):
            events.runtime_state.transition(state, reason='rapid', request_id='r1')
        snapshot = events.runtime_state.snapshot()
        assert snapshot.state is RuntimeState.SUCCESS
        assert presence.state is RuntimeState.SUCCESS
        assert presence.sequence == snapshot.sequence
        stale_sequence = snapshot.sequence - 2
        presence._on_runtime_state({'state': 'UNDERSTANDING', 'sequence': stale_sequence})
        assert presence.state is RuntimeState.SUCCESS
        assert presence.sequence == snapshot.sequence
    finally:
        presence.close()


def test_100_plus_state_events_remain_monotonic_without_duplicate_restart():
    events = EventBus()
    seen = []
    unsubscribe = events.subscribe('runtime.state', seen.append)
    try:
        for index in range(70):
            events.runtime_state.transition(RuntimeState.ACTIVE, reason=f'active-{index}')
            # Duplicate is intentionally ignored and must not restart presentation.
            events.runtime_state.transition(RuntimeState.ACTIVE, reason=f'duplicate-{index}')
            events.runtime_state.transition(RuntimeState.IDLE, reason=f'idle-{index}')
        assert len(seen) == 140
        assert [item['sequence'] for item in seen] == list(range(1, 141))
        assert events.runtime_state.snapshot().sequence == 140
    finally:
        unsubscribe()


def test_presence_mount_unmount_has_no_runtime_listener_leak(tmp_path):
    events = EventBus()
    baseline = len(events._listeners.get('runtime.state', []))
    for index in range(100):
        presence = PresenceController(events, tmp_path / f'presence-{index}.json')
        assert len(events._listeners.get('runtime.state', [])) == baseline + 1
        presence.close()
        assert len(events._listeners.get('runtime.state', [])) == baseline


class _Memory:
    path = None

    def __init__(self):
        self.messages = []

    def add_message(self, role, text, **kwargs):
        self.messages.append({'role': role, 'content': text})

    def recent_messages(self, limit, **kwargs):
        return self.messages[-limit:]

    def audit(self, *args, **kwargs):
        return None


class _Brain:
    def context(self, text, limit):
        return []

    def extract_candidates(self, text, answer):
        return []

    def remember(self, candidate):
        return None


class _Knowledge:
    def search(self, text, limit):
        return []


class _Models:
    def __init__(self, tool_name):
        self.tool_name = tool_name

    def json(self, *args, **kwargs):
        return {
            'goal': 'observe safely',
            'steps': [
                {
                    'tool': self.tool_name,
                    'description': 'read observed data',
                    'parameters': {},
                }
            ],
        }

    def chat(self, *args, **kwargs):
        return 'Verified response.'


def _real_executor(*, verified: bool):
    events = EventBus()
    settings = SimpleNamespace(autonomy_mode='act', data_dir=None)
    tools = ToolRegistry(settings)
    verifier = (lambda _params, _result: verified)
    tools.register(
        Tool(
            'observe',
            'Read an observed value',
            lambda _params: {'observed': True},
            risk=Risk.READ_ONLY,
            verifier=verifier,
        )
    )
    executor = AgentExecutor(
        models=_Models('observe'),
        tools=tools,
        memory=_Memory(),
        events=events,
        second_brain=_Brain(),
        knowledge=_Knowledge(),
    )
    return events, executor


def _run_executor_in_canonical_context(events, executor, request_id='r1'):
    """Mirror CanonicalTurnRuntime's request context around real AgentExecutor work."""
    events.emit('turn.started', request_id=request_id)
    token = set_turn_context(
        new_turn_context(
            request_id=request_id,
            conversation_id='stage5-qualification',
            owner_id='owner',
            surface='qualification',
            input_modality='text',
        )
    )
    try:
        return executor.chat('Observe the current value.')
    finally:
        reset_turn_context(token)


def test_actual_agent_operations_produce_memory_knowledge_thinking_tool_response_and_success():
    events, executor = _real_executor(verified=True)
    seen = []
    events.subscribe('runtime.state', seen.append)
    assert _run_executor_in_canonical_context(events, executor) == 'Verified response.'
    events.emit('turn.completed', request_id='r1')
    states = [item['state'] for item in seen]
    for required in (
        'MEMORY_RETRIEVAL',
        'KNOWLEDGE_RETRIEVAL',
        'THINKING',
        'TOOL_ACTION',
        'RESPONDING',
        'SUCCESS',
    ):
        assert required in states
    assert events.runtime_state.snapshot().state is RuntimeState.SUCCESS


def test_actual_unverified_agent_operation_produces_warning_and_never_success():
    events, executor = _real_executor(verified=False)
    seen = []
    events.subscribe('runtime.state', seen.append)
    assert _run_executor_in_canonical_context(events, executor) == 'Verified response.'
    events.emit('turn.completed', request_id='r1')
    states = [item['state'] for item in seen]
    assert 'WARNING' in states
    assert 'SUCCESS' not in states
    assert events.runtime_state.snapshot().state is RuntimeState.WARNING


def _run_node(source: str) -> dict:
    node = shutil.which('node')
    if not node:
        pytest.fail('Node.js is required for Stage-5 PWA behavioral qualification')
    process = subprocess.run(
        [node, '-e', source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert process.returncode == 0, process.stderr or process.stdout
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    assert lines, process.stderr
    return json.loads(lines[-1])


def _pwa_mock_prefix(queue: list[dict]) -> str:
    encoded = json.dumps(queue)
    return f"""
const fs=require('fs');
const source=fs.readFileSync('pwa/v1-runtime.js','utf8');
const queue={encoded};
const timers=[];let timerId=0;let apiCalls=0;const renders=[];const docListeners={{}};const globalListeners={{}};let visibilityRemoved=false;
const element=()=>({{classList:{{toggle:()=>{{}}}},setAttribute:()=>{{}},textContent:'',value:'',onclick:null}});
globalThis.handsFree=false;globalThis.speaking=false;globalThis.turnInFlight=false;globalThis.pendingApproval=null;
globalThis.currentConversationId=null;globalThis.currentConversationTitle='';globalThis.currentUtterance=null;
globalThis.preference=()=>true;globalThis.scheduleListening=()=>{{}};globalThis.stopRecognition=()=>{{}};
globalThis.makeUtterance=()=>({{}});globalThis.clearApproval=()=>{{}};globalThis.showApproval=()=>{{}};
globalThis.appendMessage=()=>{{}};globalThis.refreshConversationList=async()=>{{}};globalThis.createRecognition=undefined;
globalThis.sessionStorage={{getItem:()=>null,setItem:()=>{{}},removeItem:()=>{{}}}};
globalThis.crypto=require('crypto').webcrypto;
globalThis.$=()=>element();
globalThis.setState=(name,detail)=>renders.push({{name,detail}});
globalThis.document={{visibilityState:'visible',documentElement:{{dataset:{{}}}},addEventListener:(name,fn)=>{{docListeners[name]=fn}},removeEventListener:(name,fn)=>{{if(docListeners[name]===fn){{delete docListeners[name];visibilityRemoved=true}}}}}};
globalThis.addEventListener=(name,fn)=>{{globalListeners[name]=fn}};
globalThis.setTimeout=(fn,delay)=>{{const id=++timerId;timers.push({{id,fn,delay,cleared:false,fired:false}});return id}};
globalThis.clearTimeout=id=>{{const timer=timers.find(item=>item.id===id);if(timer)timer.cleared=true}};
globalThis.api=async path=>{{if(path==='/runtime-state'){{apiCalls++;const item=queue.shift();if(!item)throw new Error('missing queued runtime-state response');if(item.error)throw new Error(item.error);return item.snapshot}};return {{}}}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const fire=async()=>{{const timer=timers.find(item=>!item.fired&&!item.cleared);if(!timer)throw new Error('no pending timer');timer.fired=true;timer.fn();await flush();return timer.delay}};
"""


def test_pwa_reconnect_backoff_recovery_stale_rejection_hidden_tab_and_cleanup_are_behavioral():
    queue = [
        {'error': 'offline-1'},
        {'error': 'offline-2'},
        {'error': 'offline-3'},
        {'error': 'offline-4'},
        {'error': 'offline-5'},
        {'snapshot': {'schema_version': 1, 'state': 'THINKING', 'sequence': 203, 'request_id': 'r2', 'label': 'Thinking'}},
        {'snapshot': {'schema_version': 1, 'state': 'UNDERSTANDING', 'sequence': 201, 'request_id': 'r2', 'label': 'Understanding'}},
        {'snapshot': {'schema_version': 1, 'state': 'THINKING', 'sequence': 203, 'request_id': 'r2', 'label': 'Thinking'}},
        {'snapshot': {'schema_version': 1, 'state': 'RESPONDING', 'sequence': 204, 'request_id': 'r2', 'label': 'Responding'}},
    ]
    script = _pwa_mock_prefix(queue) + r"""
(async()=>{
  eval(source);await flush();
  const backoff=[];
  for(let i=0;i<5;i++)backoff.push(await fire());
  const recovered=globalThis.personalAiRuntimeStateSnapshot();
  const recoveryTimer=timers.find(item=>!item.fired&&!item.cleared).delay;
  const rendersAfterRecovery=renders.length;
  await fire();
  const stale=globalThis.personalAiRuntimeStateSnapshot();
  const rendersAfterStale=renders.length;
  await fire();
  const duplicate=globalThis.personalAiRuntimeStateSnapshot();
  const rendersAfterDuplicate=renders.length;
  document.visibilityState='hidden';const callsBeforeHidden=apiCalls;await fire();const hiddenNoCall=apiCalls===callsBeforeHidden;
  document.visibilityState='visible';docListeners.visibilitychange();await flush();
  const visible=globalThis.personalAiRuntimeStateSnapshot();
  globalListeners.pagehide();
  const liveTimers=timers.filter(item=>!item.fired&&!item.cleared).length;
  console.log(JSON.stringify({backoff,recoveryTimer,recovered,stale,duplicate,rendersAfterRecovery,rendersAfterStale,rendersAfterDuplicate,hiddenNoCall,visible,visibilityRemoved,liveTimers}));
})().catch(error=>{console.error(error);process.exit(1)});
"""
    result = _run_node(script)
    assert result['backoff'] == [1500, 3000, 6000, 12000, 12000]
    assert result['recoveryTimer'] == 750
    assert result['recovered']['state_sequence'] == 203
    assert result['stale']['state_sequence'] == 203
    assert result['duplicate']['state_sequence'] == 203
    assert result['rendersAfterRecovery'] == result['rendersAfterStale'] == result['rendersAfterDuplicate']
    assert result['hiddenNoCall'] is True
    assert result['visible']['state_sequence'] == 204
    assert result['visibilityRemoved'] is True
    assert result['liveTimers'] == 0


@pytest.mark.parametrize(
    'state',
    [
        'THINKING',
        'MEMORY_RETRIEVAL',
        'KNOWLEDGE_RETRIEVAL',
        'NEEDS_APPROVAL',
        'RESPONDING',
        'BACKGROUND',
    ],
)
def test_pwa_page_reload_reconstructs_backend_canonical_state(state):
    queue = [
        {
            'snapshot': {
                'schema_version': 1,
                'state': state,
                'sequence': 203,
                'request_id': 'r2',
                'label': state.replace('_', ' ').title(),
            }
        }
    ]
    script = _pwa_mock_prefix(queue) + r"""
(async()=>{
  eval(source);await flush();
  console.log(JSON.stringify({snapshot:globalThis.personalAiRuntimeStateSnapshot(),dataset:document.documentElement.dataset,renders}));
})().catch(error=>{console.error(error);process.exit(1)});
"""
    result = _run_node(script)
    assert result['snapshot']['state_sequence'] == 203
    assert result['snapshot']['request_id'] == 'r2'
    assert result['dataset']['aiState'] == state.lower()
    assert len(result['renders']) == 1


def _pulse_class_literals() -> dict[str, object]:
    tree = ast.parse((ROOT / 'ui' / 'pulse.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == 'PulseWidget':
            values = {}
            for statement in node.body:
                if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
                    name = statement.targets[0].id
                    if name in {'STATE_ALIASES', 'STATE_SPEEDS', 'STATE_ENERGY', 'STATE_AMPLITUDE'}:
                        values[name] = ast.literal_eval(statement.value)
            return values
    raise AssertionError('PulseWidget class is unavailable')


def test_reduced_motion_keeps_all_semantic_visual_states_distinguishable_headlessly():
    values = _pulse_class_literals()
    aliases = values['STATE_ALIASES']
    speeds = values['STATE_SPEEDS']
    energy = values['STATE_ENERGY']
    amplitude = values['STATE_AMPLITUDE']

    def normalize(state):
        key = str(state).strip().lower().replace('-', '_').replace(' ', '_')
        return aliases.get(key, key if key in speeds else 'warning')

    normalized = [normalize(state.value) for state in RuntimeState]
    assert len(set(normalized)) == len(RuntimeState)
    assert all(visual in speeds and visual in energy and visual in amplitude for visual in normalized)
    assert all(speeds[visual] > 0 and energy[visual] > 0 for visual in normalized)

    # Parse the implementation rather than importing Qt on a headless CI host: this
    # validates that reduced motion changes timing/amplitude while preserving state.
    tree = ast.parse((ROOT / 'ui' / 'pulse.py').read_text(encoding='utf-8'))
    pulse = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PulseWidget')
    set_reduce_motion = next(node for node in pulse.body if isinstance(node, ast.FunctionDef) and node.name == 'set_reduce_motion')
    node_position = next(node for node in pulse.body if isinstance(node, ast.FunctionDef) and node.name == '_node_position')
    reduce_constants = {node.value for node in ast.walk(set_reduce_motion) if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))}
    position_constants = {node.value for node in ast.walk(node_position) if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))}
    assert {16, 120}.issubset(reduce_constants)
    assert 0.42 in position_constants
