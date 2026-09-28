from types import SimpleNamespace
import pytest
from security.approvals import ApprovalManager
from tools.registry import ToolRegistry,Tool,Risk
from voice.realtime_tools import RealtimeToolBridge
from voice.openai_realtime import OpenAIRealtimeVoiceSession

class Memory:
    def __init__(self):self.rows=[]
    def audit(self,*args):self.rows.append(args)
class Executor:
    pass

def build_executor(mode='ask'):
    settings=SimpleNamespace(autonomy_mode=mode)
    tools=ToolRegistry(settings)
    tools.register(Tool('read_status','read',lambda p:{'ok':'read'},Risk.READ_ONLY))
    tools.register(Tool('change_state','change',lambda p:{'changed':p['value']},Risk.EXTERNAL_SIDE_EFFECT))
    ex=Executor();ex.tools=tools;ex.memory=Memory();ex.approvals=ApprovalManager();return ex

def test_realtime_read_only_executes_automatically():
    bridge=RealtimeToolBridge(build_executor('ask'))
    result=bridge.invoke('c1','read_status','{}')
    assert result['status']=='completed' and result['ok'] is True

def test_realtime_side_effect_requires_then_accepts_approval():
    bridge=RealtimeToolBridge(build_executor('ask'))
    result=bridge.invoke('c2','change_state','{"value":7}')
    assert result['status']=='approval_required' and 'c2' in bridge.pending
    approved=bridge.approve('c2')
    assert approved['ok'] is True and approved['result']['changed']==7

def test_realtime_reject_blocks_action():
    bridge=RealtimeToolBridge(build_executor('ask'))
    bridge.invoke('c3','change_state','{"value":9}')
    rejected=bridge.reject('c3')
    assert rejected['ok'] is False and 'c3' not in bridge.pending

def test_native_session_exposes_tools_and_records_metrics():
    s=SimpleNamespace(openai_api_key='x',realtime_provider='openai',realtime_model='gpt-realtime',realtime_safety_identifier='',realtime_instructions='x',realtime_reasoning_effort='low',realtime_sample_rate=24000,realtime_voice='alloy')
    ex=build_executor('ask'); session=OpenAIRealtimeVoiceSession(s,executor=ex)
    update=session.session_update()
    assert any(t['name']=='read_status' for t in update['session']['tools'])
    session.handle_event({'type':'response.created'})
    session.handle_event({'type':'response.output_audio.delta','delta':'AA=='})
    assert session.metrics['response_count']==1 and session.metrics['audio_chunks_out']==1


def test_realtime_bridge_fails_closed_without_canonical_approval_authority():
    ex=Executor()
    ex.tools=build_executor('ask').tools
    ex.memory=Memory()
    with pytest.raises(RuntimeError, match='canonical approval authority'):
        RealtimeToolBridge(ex)


def test_realtime_approval_survives_bridge_reconstruction_and_dispatches_once():
    ex=build_executor('ask')
    first=RealtimeToolBridge(ex)
    required=first.invoke('reload-call','change_state','{"value":11}')
    approval_id=required['approval_id']
    reloaded=RealtimeToolBridge(ex)
    approved=reloaded.approve('reload-call',approval_id=approval_id)
    assert approved['ok'] is True
    assert approved['result']['changed']==11
    assert approved['verified'] is False
    assert approved['verification_reason']
    replay=reloaded.approve('reload-call',approval_id=approval_id)
    assert replay['status']=='completed'
    assert replay['result']['changed']==11


def test_realtime_reconnect_requires_exact_approval_identity():
    ex=build_executor('ask')
    first=RealtimeToolBridge(ex)
    required=first.invoke('bound-call','change_state','{"value":12}')
    reloaded=RealtimeToolBridge(ex)
    with pytest.raises(PermissionError):
        reloaded.approve('bound-call')
    with pytest.raises(PermissionError):
        reloaded.approve('wrong-call',approval_id=required['approval_id'])


def test_completed_realtime_replay_cannot_be_claimed_by_different_call_id():
    ex=build_executor('ask')
    first=RealtimeToolBridge(ex)
    required=first.invoke('original-call','change_state','{"value":13}')
    approval_id=required['approval_id']
    completed=RealtimeToolBridge(ex).approve('original-call',approval_id=approval_id)
    assert completed['ok'] is True
    with pytest.raises(PermissionError):
        RealtimeToolBridge(ex).approve('attacker-call',approval_id=approval_id)


def test_realtime_audit_never_persists_raw_tool_parameters_or_exception_text():
    ex=build_executor('ask')
    bridge=RealtimeToolBridge(ex)
    bridge.invoke('secret-call','read_status','{"token":"super-secret-value"}')
    payloads=[row[2] for row in ex.memory.rows if len(row)>2 and isinstance(row[2],dict)]
    assert payloads
    assert all('params' not in payload for payload in payloads)
    assert 'super-secret-value' not in repr(payloads)


def test_realtime_cancel_after_bridge_reconstruction_rejects_durable_pending_approval():
    ex=build_executor('ask')
    first=RealtimeToolBridge(ex)
    required=first.invoke('cancel-after-reload','change_state','{"value":21}')
    approval_id=required['approval_id']
    reloaded=RealtimeToolBridge(ex)
    cancelled=reloaded.cancel_unapproved(reason='voice_stopped')
    assert 'cancel-after-reload' in cancelled
    record=ex.approvals.record(approval_id)
    assert record is not None and record['status']=='rejected'
    with pytest.raises(PermissionError):
        reloaded.approve('cancel-after-reload',approval_id=approval_id)


def test_realtime_pending_approval_is_invalidated_by_global_emergency_stop_epoch():
    ex=build_executor('ask')
    required=RealtimeToolBridge(ex).invoke('estop-call','change_state','{"value":22}')
    approval_id=required['approval_id']
    ex.approvals.advance_security_epoch()
    record=ex.approvals.record(approval_id)
    assert record is not None and record['status']=='invalidated'
    with pytest.raises(PermissionError):
        RealtimeToolBridge(ex).approve('estop-call',approval_id=approval_id)


def test_realtime_failure_does_not_expose_exception_secret_in_result_event_or_audit():
    ex=build_executor('auto')
    tool=ex.tools.get('read_status')
    ex.tools.set_autonomy_mode('act')
    secret='provider-secret-must-not-leak'
    tool.handler=lambda params: (_ for _ in ()).throw(RuntimeError(secret))
    captured=[]
    class Events:
        def emit(self, name, **data): captured.append((name, data))
    bridge=RealtimeToolBridge(ex, Events())
    result=bridge.invoke('secret-error-call','read_status','{}')
    assert result['ok'] is False
    assert secret not in repr(result)
    assert result['error_type']=='RuntimeError'
    assert secret not in repr(captured)
    payloads=[row[2] for row in ex.memory.rows if len(row)>2 and isinstance(row[2],dict)]
    assert payloads
    assert secret not in repr(payloads)


def test_realtime_authorization_receives_parameters_for_policy_evaluation():
    ex=build_executor('auto')
    seen={}
    original=ex.tools.authorize
    def capture(tool, confirmed=False, **kwargs):
        seen.update(kwargs)
        return original(tool, confirmed=confirmed, **kwargs)
    ex.tools.authorize=capture
    RealtimeToolBridge(ex).invoke('policy-params','read_status','{"scope":"private"}')
    assert seen.get('parameters')=={'scope':'private'}


def test_stage8_realtime_critical_tool_requires_fresh_reauthentication():
    ex = build_executor('ask')
    executed = []
    ex.tools.register(Tool(
        'critical_action',
        'critical',
        lambda params: executed.append(params) or {'done': True},
        Risk.CRITICAL,
        requires_reauth=True,
    ))
    result = RealtimeToolBridge(ex).invoke('critical-call', 'critical_action', '{"value":1}')
    assert result['status'] == 'reauthentication_required'
    assert result['ok'] is False
    assert executed == []
    assert ex.approvals.list_pending(owner_id='owner') == []


def test_stage8_realtime_approval_revalidates_policy_before_dispatch():
    ex = build_executor('ask')
    executed = []
    tool = ex.tools.get('change_state')
    tool.handler = lambda params: executed.append(params['value']) or {'changed': params['value']}
    bridge = RealtimeToolBridge(ex)
    required = bridge.invoke('policy-revoke-call', 'change_state', '{"value":31}')
    tool.prohibited = True

    with pytest.raises(PermissionError):
        bridge.approve('policy-revoke-call', approval_id=required['approval_id'])

    assert executed == []
    record = ex.approvals.record(required['approval_id'])
    assert record is not None and record['status'] == 'invalidated'


def test_stage8_realtime_auto_execution_reports_verification_truth():
    ex = build_executor('act')
    result = RealtimeToolBridge(ex).invoke('read-verified', 'read_status', '{}')
    assert result['ok'] is True
    assert result['verified'] is True

    reversible = Tool('reversible_change', 'reversible', lambda params: {'changed': True}, Risk.REVERSIBLE)
    ex.tools.register(reversible)
    result = RealtimeToolBridge(ex).invoke('reversible-unverified', 'reversible_change', '{}')
    assert result['ok'] is True
    assert result['verified'] is False
    assert result['verification_reason']


def test_stage8_realtime_does_not_advertise_prohibited_compatibility_tools():
    ex = build_executor('ask')
    ex.tools.register(Tool('legacy_unsafe', 'disabled compatibility path', lambda p: None, Risk.READ_ONLY, prohibited=True))
    names = {item['name'] for item in RealtimeToolBridge(ex).definitions()}
    assert 'legacy_unsafe' not in names


def test_stage8_realtime_post_dispatch_failure_requires_recovery():
    ex = build_executor('ask')
    secret = 'side-effect-may-have-happened'
    tool = ex.tools.get('change_state')
    tool.handler = lambda params: (_ for _ in ()).throw(RuntimeError(secret))
    bridge = RealtimeToolBridge(ex)
    required = bridge.invoke('uncertain-call', 'change_state', '{"value":44}')

    with pytest.raises(RuntimeError, match='recovery review'):
        bridge.approve('uncertain-call', approval_id=required['approval_id'])

    record = ex.approvals.record(required['approval_id'])
    assert record is not None
    assert record['status'] == 'recovery_required'


def test_stage8_realtime_provider_error_is_redacted():
    settings = SimpleNamespace(
        openai_api_key='x', realtime_provider='openai', realtime_model='gpt-realtime',
        realtime_safety_identifier='', realtime_instructions='x',
        realtime_reasoning_effort='low', realtime_sample_rate=24000,
        realtime_voice='alloy',
    )
    captured = []
    class Events:
        def emit(self, name, **data):
            captured.append((name, data))

    session = OpenAIRealtimeVoiceSession(settings, events=Events(), executor=None)
    session.handle_event({
        'type': 'error',
        'error': 'Authorization: Bearer super-secret-token?token=leak',
    })

    assert 'super-secret-token' not in session.metrics['last_error']
    assert 'token=leak' not in session.metrics['last_error']
    assert 'super-secret-token' not in repr(captured)
    assert '[redacted]' in session.metrics['last_error']


def test_stage8_realtime_provider_errors_are_redacted():
    captured = []
    class Events:
        def emit(self, name, **data):
            captured.append((name, data))

    s=SimpleNamespace(
        openai_api_key='x',realtime_provider='openai',realtime_model='gpt-realtime',
        realtime_safety_identifier='',realtime_instructions='x',realtime_reasoning_effort='low',
        realtime_sample_rate=24000,realtime_voice='alloy',
        voice_personality='calm',voice_speaking_rate=1.0,voice_min_endpoint_ms=420,
        voice_max_endpoint_ms=1100,voice_noise_multiplier=2.4,voice_min_threshold=.008,
        voice_max_utterance_seconds=45.0,
    )
    session=OpenAIRealtimeVoiceSession(s,events=Events(),executor=None)
    session.handle_event({
        'type':'error',
        'error':'Authorization: Bearer SUPERSECRETTOKEN123 api_key=TOPSECRET123 Cookie: sid=COOKIESECRET123',
    })
    text=repr((session.metrics, captured))
    assert 'SUPERSECRETTOKEN123' not in text
    assert 'TOPSECRET123' not in text
    assert 'COOKIESECRET123' not in text
    assert 'redacted' in text.lower()


def test_stage8_realtime_transport_error_sanitizer_bounds_and_redacts():
    secret='Bearer SUPERSECRETTOKEN123 ' + ('x' * 5000)
    safe=OpenAIRealtimeVoiceSession._safe_error(secret)
    assert 'SUPERSECRETTOKEN123' not in safe
    assert len(safe) <= 1000
