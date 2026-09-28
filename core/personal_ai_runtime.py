from __future__ import annotations
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from agent.executor import ConfirmationRequired, ExecutionCancelled, ReauthenticationRequired
from core.p10_turn_selection import P10TurnSelector
from core.turn_context import current_turn_context, new_turn_context, reset_turn_context, set_turn_context
from desktop.operator_context import OperatorRequestContext, reset_operator_request, set_operator_request

class TurnReplayBlocked(RuntimeError):
    """Existing logical turn must be resumed, not executed again."""

class CanonicalTurnRuntime:
    """Canonical V1 turn identity boundary; P10 orchestrates, P6/W7 execute."""
    HISTORY_LIMIT = 16
    CANONICAL_OWNER = 'owner'
    TERMINAL_STATUSES = frozenset({'completed', 'cancelled', 'failed'})

    def __init__(self, executor, continuity, path: Path, *, events=None):
        self._executor = executor
        self.continuity = continuity
        self.events = events
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.p10_selector = P10TurnSelector()
        self.autonomy = None
        self._cancel_lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}
        with self._con() as con:
            con.executescript("CREATE TABLE IF NOT EXISTS canonical_turns(request_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,conversation_id TEXT,device_id TEXT,session_id TEXT,surface TEXT NOT NULL,input_modality TEXT NOT NULL,privacy_level TEXT NOT NULL,risk_level TEXT NOT NULL,user_text TEXT NOT NULL,status TEXT NOT NULL,assistant_text TEXT,approval_id TEXT,error_code TEXT,p10_goal_id TEXT,p10_plan_id TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL);CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_turn_approval ON canonical_turns(approval_id) WHERE approval_id IS NOT NULL;CREATE INDEX IF NOT EXISTS idx_canonical_turn_conversation ON canonical_turns(conversation_id,created_at);")
            cols = {row[1] for row in con.execute('PRAGMA table_info(canonical_turns)')}
            if 'p10_goal_id' not in cols: con.execute('ALTER TABLE canonical_turns ADD COLUMN p10_goal_id TEXT')
            if 'p10_plan_id' not in cols: con.execute('ALTER TABLE canonical_turns ADD COLUMN p10_plan_id TEXT')

    def attach_autonomy(self, autonomy): self.autonomy = autonomy
    def _con(self):
        con = sqlite3.connect(self.path, timeout=30); con.row_factory = sqlite3.Row; return con
    def __getattr__(self, name): return getattr(self._executor, name)
    def _emit(self, event, **payload):
        if self.events: self.events.emit(event, **payload)
    def _register_cancel_event(self, request_id, supplied=None):
        event = supplied if supplied is not None and hasattr(supplied, 'is_set') and hasattr(supplied, 'set') else threading.Event()
        with self._cancel_lock: self._cancel_events[str(request_id)] = event
        return event
    def _signal_cancel(self, request_id):
        with self._cancel_lock: event = self._cancel_events.get(str(request_id))
        if event is not None: event.set()
    def _release_cancel_event(self, request_id, event):
        with self._cancel_lock:
            if self._cancel_events.get(str(request_id)) is event:
                self._cancel_events.pop(str(request_id), None)
    @staticmethod
    def _check_cooperative_cancel(kwargs):
        event = kwargs.get('cancel_event')
        if event is not None and event.is_set():
            raise ExecutionCancelled('canonical turn cancelled')
    @staticmethod
    def _clean_text(text):
        value = str(text or '').strip()
        if not value: raise ValueError('turn text is required')
        return value
    def _security_epoch(self):
        approvals = getattr(self._executor, 'approvals', None); provider = getattr(approvals, 'current_security_epoch', None)
        try: return int(provider()) if callable(provider) else 0
        except Exception: return 0
    @classmethod
    def _owner(cls, owner_id):
        owner = str(owner_id or cls.CANONICAL_OWNER)
        if owner != cls.CANONICAL_OWNER: raise PermissionError('Personal AI V1 is single-owner; alternate owner identity is forbidden')
        return owner
    def _existing(self, request_id):
        with self._con() as con: row = con.execute('SELECT * FROM canonical_turns WHERE request_id=?', (request_id,)).fetchone()
        return dict(row) if row else None
    def turn(self, request_id: str):
        row = self._existing(str(request_id))
        if row is None: return None
        return {key: row.get(key) for key in ('request_id','owner_id','conversation_id','device_id','session_id','surface','input_modality','privacy_level','risk_level','user_text','status','assistant_text','approval_id','error_code','p10_goal_id','p10_plan_id','created_at','updated_at')}
    def _turn_by_approval(self, approval_id):
        with self._con() as con: row = con.execute('SELECT * FROM canonical_turns WHERE approval_id=?', (approval_id,)).fetchone()
        return dict(row) if row else None
    def _resolve_conversation(self, *, device_id, conversation_id, surface):
        if self.continuity is None: return str(conversation_id or '')
        if conversation_id:
            thread = self.continuity.thread(str(conversation_id))
            if not thread or thread.get('closed_at'): raise KeyError('active conversation is unavailable')
            if device_id: self.continuity.set_active(device_id, thread['id'])
            return str(thread['id'])
        bundle = self.continuity.resume(str(device_id or f'local:{surface or "runtime"}'), event_limit=self.HISTORY_LIMIT*2)
        resolved = str((bundle.get('thread') or {}).get('id') or '')
        if not resolved: raise RuntimeError('continuity failed to establish a conversation')
        return resolved
    def _history(self, conversation_id, explicit_history):
        if explicit_history is not None:
            return [{'role':str(i.get('role')),'content':str(i.get('content'))} for i in list(explicit_history)[-self.HISTORY_LIMIT:] if isinstance(i,dict) and i.get('role') in {'user','assistant'} and str(i.get('content') or '').strip()]
        return None if self.continuity is None or not conversation_id else self.continuity.conversation_history(conversation_id, limit=self.HISTORY_LIMIT)
    def _append(self, conversation_id, *, device_id, kind, text, event_id):
        if self.continuity is None or not conversation_id: return None
        return self.continuity.append(conversation_id, device_id=device_id, kind=kind, payload={'text':str(text)}, event_id=event_id)

    def _claim_started(self, **values):
        """Atomically claim request ownership in durable SQLite storage."""
        stamp = time.time()
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM canonical_turns WHERE request_id=?', (values['request_id'],)).fetchone()
            if row is not None: return False, dict(row)
            con.execute("""INSERT INTO canonical_turns(request_id,owner_id,conversation_id,device_id,session_id,surface,input_modality,privacy_level,risk_level,user_text,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'started',?,?)""", (values['request_id'],values['owner_id'],values['conversation_id'] or None,values['device_id'],values['session_id'],values['surface'],values['input_modality'],values['privacy_level'],values['risk_level'],values['user_text'],stamp,stamp))
        return True, None

    def _insert_started(self, **values):
        """Compatibility seeding helper backed by the durable atomic claim path."""
        claimed, _ = self._claim_started(**values)
        if not claimed:
            raise sqlite3.IntegrityError('UNIQUE constraint failed: canonical_turns.request_id')

    def _update(self, request_id, status, *, assistant_text=None, approval_id=None, error_code=None, p10_goal_id=None, p10_plan_id=None):
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT status FROM canonical_turns WHERE request_id=?', (request_id,)).fetchone()
            if row is None: raise KeyError(f'canonical request {request_id} is unavailable')
            current = str(row['status'])
            if current in self.TERMINAL_STATUSES and current != status: return False
            con.execute('''UPDATE canonical_turns SET status=?,assistant_text=COALESCE(?,assistant_text),approval_id=COALESCE(?,approval_id),error_code=?,p10_goal_id=COALESCE(?,p10_goal_id),p10_plan_id=COALESCE(?,p10_plan_id),updated_at=? WHERE request_id=?''', (status,assistant_text,approval_id,error_code,p10_goal_id,p10_plan_id,time.time(),request_id))
        return True
    def _replay_conflict(self, request_id, reason):
        self._emit('turn.replay_conflict', request_id=request_id, reason=reason); raise PermissionError(reason)
    def _validate_replay(self, existing, *, text, owner_id, device_id, session_id, conversation_id):
        request_id = existing['request_id']
        if existing['owner_id'] != owner_id or existing['user_text'] != text: self._replay_conflict(request_id, 'request_id is already bound to different turn content or authority')
        if (existing.get('device_id') or None) != (device_id or None): self._replay_conflict(request_id, 'request_id is already bound to a different device')
        if session_id and existing.get('session_id') and existing['session_id'] != session_id: self._replay_conflict(request_id, 'request_id is already bound to a different trusted session')
        if conversation_id and existing.get('conversation_id') and existing['conversation_id'] != conversation_id: self._replay_conflict(request_id, 'request_id is already bound to a different conversation')
        if existing['status'] == 'completed':
            answer = str(existing.get('assistant_text') or ''); self._emit('turn.replayed', request_id=request_id, status='completed'); return answer
        self._emit('turn.replay_blocked', request_id=request_id, status=str(existing.get('status') or 'unknown'))
        raise TurnReplayBlocked(f"request {request_id} is {existing['status']}; resume its governed lifecycle instead of duplicating work")

    def cancel_active_turns(self, *, reason='emergency_stop'):
        with self._con() as con:
            rows = con.execute("SELECT request_id,conversation_id FROM canonical_turns WHERE status NOT IN ('completed','failed','cancelled')").fetchall()
        cancelled = 0
        for row in rows:
            self._signal_cancel(row['request_id'])
            changed = self._update(str(row['request_id']), 'cancelled', error_code=str(reason or 'cancelled')[:80])
            if changed:
                cancelled += 1
                self._emit('turn.cancelled', request_id=str(row['request_id']), conversation_id=row['conversation_id'], reason=str(reason or 'cancelled')[:80])
        return cancelled

    def cancel_device_turns(self, device_id, *, reason='device_revoked'):
        device_id = str(device_id or '').strip()
        if not device_id: return 0
        with self._con() as con:
            rows = con.execute(
                "SELECT request_id,conversation_id FROM canonical_turns WHERE device_id=? AND status NOT IN ('completed','failed','cancelled')",
                (device_id,),
            ).fetchall()
        cancelled = 0
        for row in rows:
            self._signal_cancel(row['request_id'])
            changed = self._update(str(row['request_id']), 'cancelled', error_code=str(reason or 'device_revoked')[:80])
            if changed:
                cancelled += 1
                self._emit('turn.cancelled', request_id=str(row['request_id']), conversation_id=row['conversation_id'], reason=str(reason or 'device_revoked')[:80])
        return cancelled

    def cancel_session_turns(self, session_id, *, reason='session_revoked'):
        session_id = str(session_id or '').strip()
        if not session_id: return 0
        with self._con() as con:
            rows = con.execute(
                "SELECT request_id,conversation_id FROM canonical_turns WHERE session_id=? AND status NOT IN ('completed','failed','cancelled')",
                (session_id,),
            ).fetchall()
        cancelled = 0
        for row in rows:
            self._signal_cancel(row['request_id'])
            changed = self._update(str(row['request_id']), 'cancelled', error_code=str(reason or 'session_revoked')[:80])
            if changed:
                cancelled += 1
                self._emit('turn.cancelled', request_id=str(row['request_id']), conversation_id=row['conversation_id'], reason=str(reason or 'session_revoked')[:80])
        return cancelled

    def cancel_turn(self, request_id, *, owner_id=CANONICAL_OWNER, device_id=None, session_id=None):
        owner_id = self._owner(owner_id); existing = self._existing(str(request_id))
        if existing is None: return None
        if existing['owner_id'] != owner_id: raise PermissionError('request is not bound to this owner')
        if device_id and existing.get('device_id') and existing['device_id'] != device_id: raise PermissionError('request is not bound to this trusted device')
        if session_id and existing.get('session_id') and existing['session_id'] != session_id: raise PermissionError('request is not bound to this trusted session')
        if existing['status'] in self.TERMINAL_STATUSES: return self.turn(str(request_id))
        self._signal_cancel(request_id)
        changed = self._update(str(request_id),'cancelled',error_code='cancelled')
        if changed: self._emit('turn.cancelled',request_id=str(request_id),conversation_id=existing.get('conversation_id'),reason='owner_cancelled')
        return self.turn(str(request_id))

    def _bind_context(self, *, request_id, conversation_id, owner_id, device_id, session_id, surface, input_modality, privacy_level, risk_level, refs):
        existing = current_turn_context()
        if existing is not None and existing.request_id == request_id: return None, None
        turn = new_turn_context(request_id=request_id,conversation_id=conversation_id,owner_id=owner_id,device_id=device_id or '',session_id=session_id or '',security_epoch=self._security_epoch(),surface=surface,input_modality=input_modality,privacy_level=privacy_level,risk_level=risk_level,memory_refs=refs.get('memory_refs') or (),knowledge_refs=refs.get('knowledge_refs') or (),p7_observation_refs=refs.get('p7_observation_refs') or (),p8_continuity_refs=(conversation_id,) if conversation_id else (),model_routing_refs=refs.get('model_routing_refs') or (),p10_goal_refs=refs.get('p10_goal_refs') or (),tool_refs=refs.get('tool_refs') or (),approval_refs=refs.get('approval_refs') or (),verification_refs=refs.get('verification_refs') or (),recovery_refs=refs.get('recovery_refs') or ())
        return set_turn_context(turn), set_operator_request(OperatorRequestContext(owner_id=owner_id,device_id=str(device_id or ''),session_id=str(session_id or ''),security_epoch=self._security_epoch(),conversation_id=conversation_id,workflow_id=str(refs.get('workflow_id') or ''),reauthenticated_at=refs.get('reauthenticated_at')))
    @staticmethod
    def _reset_context(tokens):
        if tokens[1] is not None: reset_operator_request(tokens[1])
        if tokens[0] is not None: reset_turn_context(tokens[0])

    def _orchestrate(self, text, *, request_id, owner_id, device_id, session_id, privacy_level, risk_level, kwargs):
        self._check_cooperative_cancel(kwargs)
        selection = self.p10_selector.select(text,explicit_background=bool(kwargs.get('background',False)),requested_actions=int(kwargs.pop('requested_actions',0) or 0))
        self._emit('turn.orchestration_selected',request_id=request_id,use_p10=selection.use_p10,reason=selection.reason,signals=list(selection.signals))
        if not selection.use_p10: return None
        if self.autonomy is None: raise RuntimeError('P10 selected but canonical AdvancedAutonomy is unavailable')
        goal = self.autonomy.create_goal(text,owner_id=owner_id,desired_outcome='Complete the owner request through governed operations and return the verified outcome to this turn.',request_id=request_id,session_id=session_id,privacy=privacy_level,risk=risk_level)
        self._update(request_id,'planning',p10_goal_id=goal['id'])
        plan = self.autonomy.propose_plan_with_model(goal['id'],owner_id=owner_id,device_trusted=bool(device_id),session_fresh=bool(session_id))
        self._update(request_id,'orchestrating',p10_goal_id=goal['id'],p10_plan_id=plan['id']); self._emit('turn.p10_bound',request_id=request_id,goal_id=goal['id'],plan_id=plan['id'])
        while True:
            self._check_cooperative_cancel(kwargs)
            ready = self.autonomy.ready_tasks(plan['id'],owner_id=owner_id)
            if not ready: break
            for task in ready:
                plan = self.autonomy.execute_task(plan['id'],task['id'],owner_id=owner_id,device_id=device_id,session_id=session_id,reauthenticated_at=kwargs.get('reauthenticated_at'),background=bool(kwargs.get('background',False)))
                current = next(x for x in plan['tasks'] if x['id']==task['id'])
                if current.get('status')=='WAITING_APPROVAL':
                    approval=current.get('approval_ref'); self._update(request_id,'needs_approval',approval_id=approval,p10_goal_id=goal['id'],p10_plan_id=plan['id']); self._emit('turn.needs_approval',request_id=request_id,approval_id=approval,goal_id=goal['id'],plan_id=plan['id']); raise TurnReplayBlocked('P10 turn is waiting for canonical owner approval')
                if plan.get('state') in {'UNCERTAIN','FAILED','CANCELLED','BLOCKED'}: raise RuntimeError(f"P10 governed plan ended in {plan.get('state')}")
        final = self.autonomy.plan(plan['id'],owner_id=owner_id)
        if final.get('state')!='COMPLETED': raise RuntimeError(f"P10 plan stopped in {final.get('state')}")
        return f"Orchestration completed (goal {goal['id']}, plan {plan['id']})."

    def chat(self, text, **kwargs):
        user_text=self._clean_text(text); owner_id=self._owner(kwargs.pop('owner_id',self.CANONICAL_OWNER)); request_id=str(kwargs.pop('request_id',None) or uuid.uuid4()); device_id=kwargs.get('device_id'); session_id=kwargs.get('session_id'); requested_conversation=kwargs.get('conversation_id'); surface=str(kwargs.pop('surface',None) or ('desktop' if not device_id else 'device')); input_modality=str(kwargs.pop('input_modality',None) or 'text'); privacy_level=str(kwargs.pop('privacy_level',None) or 'normal'); risk_level=str(kwargs.pop('risk_level',None) or 'low')
        refs={key:kwargs.pop(key,()) for key in ('memory_refs','knowledge_refs','p7_observation_refs','model_routing_refs','p10_goal_refs','tool_refs','approval_refs','verification_refs','recovery_refs')}; refs['workflow_id']=kwargs.pop('workflow_id',''); refs['reauthenticated_at']=kwargs.get('reauthenticated_at')
        existing=self._existing(request_id)
        if existing is not None: return self._validate_replay(existing,text=user_text,owner_id=owner_id,device_id=device_id,session_id=session_id,conversation_id=requested_conversation)
        conversation_id=self._resolve_conversation(device_id=device_id,conversation_id=requested_conversation,surface=surface)
        claimed,existing=self._claim_started(request_id=request_id,owner_id=owner_id,conversation_id=conversation_id,device_id=device_id,session_id=session_id,surface=surface,input_modality=input_modality,privacy_level=privacy_level,risk_level=risk_level,user_text=user_text)
        if not claimed: return self._validate_replay(existing,text=user_text,owner_id=owner_id,device_id=device_id,session_id=session_id,conversation_id=requested_conversation)
        history=self._history(conversation_id,kwargs.pop('conversation_history',None)); kwargs['conversation_id']=conversation_id or None
        if history is not None: kwargs['conversation_history']=history
        kwargs['owner_id']=owner_id
        cancel_event=self._register_cancel_event(request_id, kwargs.get('cancel_event'))
        kwargs['cancel_event']=cancel_event
        self._append(conversation_id,device_id=device_id,kind='user_message',text=user_text,event_id=f'{request_id}:user')
        self._emit('turn.started',request_id=request_id,conversation_id=conversation_id,device_id=device_id,surface=surface,input_modality=input_modality)
        tokens=self._bind_context(request_id=request_id,conversation_id=conversation_id,owner_id=owner_id,device_id=device_id,session_id=session_id,surface=surface,input_modality=input_modality,privacy_level=privacy_level,risk_level=risk_level,refs=refs)
        try:
            answer=self._orchestrate(user_text,request_id=request_id,owner_id=owner_id,device_id=device_id,session_id=session_id,privacy_level=privacy_level,risk_level=risk_level,kwargs=kwargs)
            if answer is None: answer=self._executor.chat(user_text,**kwargs)
        except ConfirmationRequired as exc:
            self._update(request_id,'needs_approval',approval_id=exc.approval_id); self._emit('turn.needs_approval',request_id=request_id,conversation_id=conversation_id,approval_id=exc.approval_id); raise
        except ReauthenticationRequired:
            self._update(request_id,'needs_reauthentication',error_code='reauthentication_required'); self._emit('turn.needs_reauthentication',request_id=request_id,conversation_id=conversation_id); raise
        except ExecutionCancelled:
            self._update(request_id,'cancelled',error_code='cancelled'); self._emit('turn.cancelled',request_id=request_id,conversation_id=conversation_id); raise
        except TurnReplayBlocked: raise
        except Exception as exc:
            self._update(request_id,'failed',error_code=type(exc).__name__); self._emit('turn.failed',request_id=request_id,conversation_id=conversation_id,error_type=type(exc).__name__); raise
        finally:
            self._reset_context(tokens)
            self._release_cancel_event(request_id, cancel_event)
        answer=str(answer)
        if not self._update(request_id,'completed',assistant_text=answer):
            current=self._existing(request_id)
            if current and current.get('status')=='cancelled': raise ExecutionCancelled('turn completed after owner cancellation')
            raise TurnReplayBlocked(f'request {request_id} changed state before completion')
        self._append(conversation_id,device_id=device_id,kind='assistant_message',text=answer,event_id=f'{request_id}:assistant'); self._emit('turn.completed',request_id=request_id,conversation_id=conversation_id); return answer

    def _approval_call(self, approval_id, callback, **kwargs):
        owner_id=self._owner(kwargs.get('owner_id',self.CANONICAL_OWNER)); turn=self._turn_by_approval(approval_id)
        if turn is None: return callback(**kwargs)
        if turn['owner_id']!=owner_id: raise PermissionError('approval is not bound to this owner')
        if kwargs.get('device_id') and kwargs['device_id']!=turn.get('device_id'): raise PermissionError('approval is not bound to this device')
        if turn.get('status') in self.TERMINAL_STATUSES: raise TurnReplayBlocked(f"request {turn['request_id']} is already {turn['status']}")
        tokens=self._bind_context(request_id=turn['request_id'],conversation_id=str(turn.get('conversation_id') or ''),owner_id=owner_id,device_id=turn.get('device_id'),session_id=turn.get('session_id'),surface=str(turn.get('surface') or 'device'),input_modality='approval',privacy_level=str(turn.get('privacy_level') or 'normal'),risk_level=str(turn.get('risk_level') or 'low'),refs={'approval_refs':(approval_id,),'reauthenticated_at':kwargs.get('reauthenticated_at')})
        try: reply=callback(**kwargs)
        except ConfirmationRequired as exc: self._update(turn['request_id'],'needs_approval',approval_id=exc.approval_id); raise
        except ReauthenticationRequired: self._update(turn['request_id'],'needs_reauthentication',error_code='reauthentication_required'); raise
        except Exception as exc: self._update(turn['request_id'],'failed',error_code=type(exc).__name__); raise
        finally: self._reset_context(tokens)
        answer=str(reply)
        if not self._update(turn['request_id'],'completed',assistant_text=answer):
            current=self._existing(turn['request_id'])
            if current and current.get('status')=='cancelled': raise ExecutionCancelled('approval completed after owner cancellation')
            raise TurnReplayBlocked(f"request {turn['request_id']} changed state before approval completion")
        self._append(str(turn.get('conversation_id') or ''),device_id=turn.get('device_id'),kind='assistant_message',text=answer,event_id=f"{turn['request_id']}:assistant"); self._emit('turn.completed',request_id=turn['request_id'],conversation_id=turn.get('conversation_id')); return reply
    def approve(self,approval_id,**kwargs): return self._approval_call(approval_id,lambda **call_kwargs:self._executor.approve(approval_id,**call_kwargs),**kwargs)
    def reject(self,approval_id,**kwargs): return self._approval_call(approval_id,lambda **call_kwargs:self._executor.reject(approval_id,**call_kwargs),**kwargs)