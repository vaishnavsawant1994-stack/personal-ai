import base64,json
from types import SimpleNamespace
from voice.openai_realtime import OpenAIRealtimeVoiceSession

def settings(**overrides):
    base=dict(openai_api_key='sk-test',realtime_provider='openai',realtime_model='gpt-realtime-2.1',realtime_voice='marin',realtime_reasoning_effort='low',realtime_safety_identifier='user-hash',realtime_instructions='Be brief.',realtime_sample_rate=24000)
    base.update(overrides);return SimpleNamespace(**base)

class Events:
    def __init__(self):self.items=[]
    def emit(self,name,**kw):self.items.append((name,kw))

class WS:
    def __init__(self):self.sent=[]
    def send(self,x):self.sent.append(json.loads(x))

def test_ga_headers_have_no_beta_header():
    s=OpenAIRealtimeVoiceSession(settings())
    assert 'Authorization: Bearer sk-test' in s.headers()
    assert all('OpenAI-Beta' not in h for h in s.headers())

def test_session_uses_audio_pcm_24k_semantic_vad():
    event=OpenAIRealtimeVoiceSession(settings()).session_update();session=event['session']
    assert event['type']=='session.update'
    assert session['model']=='gpt-realtime-2.1'
    assert session['audio']['input']['format']=={'type':'audio/pcm','rate':24000}
    assert session['audio']['input']['turn_detection']['type']=='semantic_vad'
    assert session['audio']['output']['voice']=='marin'

def test_audio_append_is_base64_pcm_bytes():
    event=OpenAIRealtimeVoiceSession.append_event(b'\x01\x02')
    assert event=={'type':'input_audio_buffer.append','audio':base64.b64encode(b'\x01\x02').decode('ascii')}

def test_audio_delta_queues_decoded_bytes_and_transcript_event():
    ev=Events();s=OpenAIRealtimeVoiceSession(settings(),ev)
    s.handle_event({'type':'response.output_audio.delta','delta':base64.b64encode(b'abc').decode()})
    assert s._play_q.get_nowait()==b'abc'
    s.handle_event({'type':'response.output_audio_transcript.delta','delta':'hello'})
    assert ('voice.reply.delta',{'text':'hello'}) in ev.items

def test_barge_in_cancels_active_response_and_drops_buffered_audio():
    ev=Events();s=OpenAIRealtimeVoiceSession(settings(),ev);ws=WS();s._ws=ws;s._response_active=True;s._play_q.put(b'old')
    s.handle_event({'type':'input_audio_buffer.speech_started'})
    assert {'type':'response.cancel'} in ws.sent
    assert s._play_q.empty() and not s._response_active
    assert any(name=='voice.barge_in' for name,_ in ev.items)

def test_native_backend_requires_key_and_provider():
    assert not OpenAIRealtimeVoiceSession(settings(openai_api_key='')).enabled
    assert not OpenAIRealtimeVoiceSession(settings(realtime_provider='local')).enabled
