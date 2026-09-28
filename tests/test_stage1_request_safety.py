from __future__ import annotations
import json, threading
from pathlib import Path
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from agent.executor import ExecutionCancelled
from core.events import EventBus
from core.personal_ai_runtime import CanonicalTurnRuntime, TurnReplayBlocked
from devices.continuity import ContinuityService
from security.pwa_sessions import PwaSessionStore
from server.logical_request_middleware import LogicalRequestMiddleware, MAX_LOGICAL_TURN_BODY
from server.pwa_session_middleware import PwaSessionMiddleware
from server.request_aware_pwa_state import RequestAwareIphonePwaState
from server.session_bound_executor import SessionBoundExecutor

RID='550e8400-e29b-41d4-a716-446655440000'; RID2='123e4567-e89b-42d3-a456-426614174000'

class Approvals:
    current_security_epoch=lambda self:7
class Executor:
    def __init__(self,block=False):self.approvals=Approvals();self.calls=0;self.block=block;self.entered=threading.Event();self.release=threading.Event()
    def chat(self,text,**kwargs):
        self.calls+=1
        if self.block:self.entered.set();assert self.release.wait(5)
        return 'answer'
class Registry:
    def is_active(self,d):return d=='d1'
    def authorize(self,d,s):return d=='d1' and s=='ai:chat'

def rt(tmp_path,executor=None,events=None):
    c=ContinuityService(tmp_path/'continuity.sqlite3',events=events);e=executor or Executor()
    return CanonicalTurnRuntime(e,c,tmp_path/'turns.sqlite3',events=events),c,e

def kinds(c):
    t=c.active_for_device('d1');return [] if not t else [x['kind'] for x in c.events_for_thread(t['id'])]

def test_database_concurrency_one_owner_and_completed_replay(tmp_path):
    e1=Executor(block=True);c=ContinuityService(tmp_path/'continuity.sqlite3');path=tmp_path/'turns.sqlite3'
    r1=CanonicalTurnRuntime(e1,c,path);e2=Executor();r2=CanonicalTurnRuntime(e2,c,path);errors=[]
    def work():
        try:r1.chat('hello',request_id=RID,device_id='d1',session_id='s1')
        except Exception as exc:errors.append(exc)
    th=threading.Thread(target=work);th.start();assert e1.entered.wait(5)
    with pytest.raises(TurnReplayBlocked):r2.chat('hello',request_id=RID,device_id='d1',session_id='s1')
    assert e2.calls==0;e1.release.set();th.join(5);assert not errors
    assert r2.chat('hello',request_id=RID,device_id='d1',session_id='s1')=='answer'
    assert e1.calls==1 and e2.calls==0 and kinds(c)==['user_message','assistant_message']

def test_runtime_reconstruction_returns_durable_result(tmp_path):
    r,c,e=rt(tmp_path);r.chat('hello',request_id=RID,device_id='d1')
    e2=Executor();r2=CanonicalTurnRuntime(e2,c,tmp_path/'turns.sqlite3')
    assert r2.chat('hello',request_id=RID,device_id='d1')=='answer' and e2.calls==0

def test_conflicting_text_device_session_conversation_fail_closed(tmp_path):
    r,c,e=rt(tmp_path);c1=c.create_thread('c1',device_id='d1')
    r.chat('hello',request_id=RID,device_id='d1',session_id='s1',conversation_id=c1)
    for text,kw in [('different',dict(device_id='d1',session_id='s1',conversation_id=c1)),('hello',dict(device_id='d2',session_id='s1',conversation_id=c1)),('hello',dict(device_id='d1',session_id='s2',conversation_id=c1))]:
        with pytest.raises(PermissionError):r.chat(text,request_id=RID,**kw)
    c2=c.create_thread('c2',device_id='d2')
    with pytest.raises(PermissionError):r.chat('hello',request_id=RID,device_id='d1',session_id='s1',conversation_id=c2)
    assert e.calls==1

def test_cancellation_fences_late_completion_and_replay(tmp_path):
    e=Executor(block=True);c=ContinuityService(tmp_path/'continuity.sqlite3');path=tmp_path/'turns.sqlite3'
    worker=CanonicalTurnRuntime(e,c,path);control=CanonicalTurnRuntime(Executor(),c,path);caught=[]
    def work():
        try:worker.chat('work',request_id=RID,device_id='d1',session_id='s1')
        except Exception as exc:caught.append(exc)
    th=threading.Thread(target=work);th.start();assert e.entered.wait(5)
    assert control.cancel_turn(RID,device_id='d1',session_id='s1')['status']=='cancelled'
    e.release.set();th.join(5);assert len(caught)==1 and isinstance(caught[0],ExecutionCancelled)
    assert worker.turn(RID)['status']=='cancelled' and kinds(c)==['user_message']
    with pytest.raises(TurnReplayBlocked):control.chat('work',request_id=RID,device_id='d1',session_id='s1')

def test_duplicate_transport_shares_cancel_token(monkeypatch):
    import server.request_aware_pwa_state as m
    current={'id':RID};monkeypatch.setattr(m,'current_logical_request_id',lambda:current['id']);cancelled=[]
    s=RequestAwareIphonePwaState(cancel_turn=cancelled.append);a=s.begin_turn('d1');b=s.begin_turn('d1')
    assert a is b and not a.is_set();current['id']=RID2;c=s.begin_turn('d1');assert a.is_set() and c is not a
    assert s.cancel('d1') and c.is_set() and cancelled==[RID2]

def http_client(tmp_path,drop=False):
    events=EventBus();r,c,e=rt(tmp_path,events=events);bound=SessionBoundExecutor(r,continuity=c,surface='iphone-pwa')
    sessions=PwaSessionStore(tmp_path/'sessions.sqlite3');token,session=sessions.issue('d1');app=FastAPI();flag={'drop':drop}
    @app.post('/iphone/api/voice/turn')
    async def turn(request:Request):
        body=await request.json();answer=bound.chat(body['transcript'],input_modality='voice')
        if flag['drop']:flag['drop']=False;raise HTTPException(503,'simulated lost response')
        return {'reply':answer}
    app.add_middleware(LogicalRequestMiddleware);app.add_middleware(PwaSessionMiddleware,sessions=sessions,device_registry=Registry(),cookie_max_age=3600)
    client=TestClient(app,base_url='https://testserver');client.cookies.set('pa_device','d1',path='/iphone');client.cookies.set('pa_session',token,path='/iphone')
    return client,r,c,e,session

def test_real_http_lost_response_retry_is_exactly_once(tmp_path):
    client,r,c,e,session=http_client(tmp_path,True);body={'request_id':RID,'transcript':'hello'}
    assert client.post('/iphone/api/voice/turn',json=body).status_code==503
    assert r.turn(RID)['status']=='completed'
    response=client.post('/iphone/api/voice/turn',json=body);assert response.status_code==200 and response.json()['reply']=='answer'
    assert e.calls==1 and kinds(c)==['user_message','assistant_message'] and r.turn(RID)['session_id']==session.id

def test_wire_boundary_rejects_spoofed_authority_and_bad_bodies(tmp_path):
    client,_,_,e,_=http_client(tmp_path)
    bad=[{}, {'request_id':'bad','transcript':'x'}, {'request_id':RID,'transcript':'x','owner_id':'attacker'}, {'request_id':RID,'transcript':'x','device_id':'d2'}, {'request_id':RID,'transcript':'x','session_id':'s2'}]
    for body in bad:assert client.post('/iphone/api/voice/turn',json=body).status_code==422
    assert client.post('/iphone/api/voice/turn',content=b'bad-json').status_code==422 and e.calls==0

def test_body_zero_exact_max_and_max_plus_one(tmp_path):
    client,_,_,e,_=http_client(tmp_path);assert client.post('/iphone/api/voice/turn',content=b'').status_code==422
    raw=json.dumps({'request_id':RID,'transcript':'hello'},separators=(',',':')).encode();exact=raw+b' '*(MAX_LOGICAL_TURN_BODY-len(raw))
    assert client.post('/iphone/api/voice/turn',content=exact,headers={'content-type':'application/json'}).status_code==200 and e.calls==1
    assert client.post('/iphone/api/voice/turn',content=exact+b' ',headers={'content-type':'application/json'}).status_code==413 and e.calls==1

def test_request_scoped_state_ignores_late_r1_after_r2():
    events=EventBus();stale=[];events.subscribe('runtime.state.stale_ignored',stale.append)
    events.emit('turn.started',request_id=RID);events.emit('state',state='thinking',request_id=RID);events.emit('turn.started',request_id=RID2)
    before=events.runtime_state.snapshot();events.emit('turn.completed',request_id=RID);after=events.runtime_state.snapshot()
    assert before.request_id==RID2 and after.request_id==RID2 and after.sequence==before.sequence and stale[-1]['request_id']==RID

def test_state_events_inside_turn_inherit_request_id(tmp_path):
    events=EventBus()
    class Stateful(Executor):
        def chat(self,text,**kwargs):self.calls+=1;events.emit('state',state='thinking');return 'answer'
    r,_,e=rt(tmp_path,Stateful(),events);r.chat('hello',request_id=RID,device_id='d1')
    assert events.runtime_state.snapshot().request_id==RID and e.calls==1

def test_pending_browser_transport_is_bounded_and_cryptographic():
    src=Path('pwa/v1-runtime.js').read_text();compact=src.replace(' ','')
    assert 'MAX_PENDING_AGE_MS=15*60*1000' in compact and 'request_id:pending.request_id' in src
    assert 'c.getRandomValues(b)' in src and 'Math.random' not in src
