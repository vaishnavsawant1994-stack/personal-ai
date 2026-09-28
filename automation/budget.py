from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_POLICY = {
    'max_runtime_seconds': 900,
    'max_steps': 50,
    'max_retries': 20,
    'max_concurrent_runs': 2,
    'max_model_calls': 100,
    'max_tool_calls': 50,
    'max_input_tokens': None,
    'max_output_tokens': None,
    'max_total_tokens': None,
    'max_cost': None,
    'approval_threshold': 'consequential',
    'execution_deadline': None,
    'cancellation_grace_seconds': 10,
    'owner_override_allowed': False,
}

_LIMITS = {
    'max_runtime_seconds': (1, 86400), 'max_steps': (1, 500), 'max_retries': (0, 100),
    'max_concurrent_runs': (1, 32), 'max_model_calls': (0, 10000), 'max_tool_calls': (0, 10000),
    'max_input_tokens': (1, 100_000_000), 'max_output_tokens': (1, 100_000_000),
    'max_total_tokens': (1, 200_000_000), 'max_cost': (0.000001, 1_000_000.0),
    'cancellation_grace_seconds': (0, 3600),
}

class WorkflowBudgetError(RuntimeError):
    code = 'workflow_limit_reached'
    user_message = 'Workflow limit reached'
    def __init__(self, reason: str, *, code: str | None = None, user_message: str | None = None):
        super().__init__(reason); self.reason = reason
        if code: self.code = code
        if user_message: self.user_message = user_message

class WorkflowRecoveryRequired(WorkflowBudgetError):
    code = 'workflow_recovery_required'; user_message = 'Recovery review required'

@dataclass
class BudgetContext:
    manager: 'WorkflowBudgetManager'; run_id: str; step_index: int; attempt: int; phase: str; ordinals: dict[str, int]

_ACTIVE: ContextVar[BudgetContext | None] = ContextVar('personal_ai_workflow_budget', default=None)
def current_budget_context(): return _ACTIVE.get()
def _now(): return datetime.now(timezone.utc).isoformat()
def _ts(): return time.time()

def normalize_policy(policy: dict | None) -> dict:
    raw = dict(policy or {}); unknown = set(raw) - set(DEFAULT_POLICY)
    if unknown: raise ValueError(f'unsupported workflow policy fields: {", ".join(sorted(unknown))}')
    result = dict(DEFAULT_POLICY); result.update(raw)
    for name, (lo, hi) in _LIMITS.items():
        value = result.get(name)
        if value is None and name in {'max_input_tokens','max_output_tokens','max_total_tokens','max_cost'}: continue
        try: numeric = float(value) if name == 'max_cost' else int(value)
        except (TypeError, ValueError) as exc: raise ValueError(f'{name} must be numeric') from exc
        if numeric < lo or numeric > hi: raise ValueError(f'{name} must be between {lo} and {hi}')
        result[name] = numeric
    if result['approval_threshold'] not in {'read_only','reversible','consequential','destructive','critical'}:
        raise ValueError('approval_threshold is invalid')
    result['owner_override_allowed'] = bool(result['owner_override_allowed'])
    if result.get('execution_deadline') is not None:
        try:
            parsed = datetime.fromisoformat(str(result['execution_deadline']).replace('Z','+00:00'))
            if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
            result['execution_deadline'] = parsed.astimezone(timezone.utc).isoformat()
        except ValueError as exc: raise ValueError('execution_deadline must be ISO-8601') from exc
    return result

class WorkflowBudgetManager:
    def __init__(self, path: Path, *, events=None, audit=None):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = events; self.audit = audit; self._install_lock = threading.RLock(); self._init_db(); self._recover_uncertain_dispatches()
    def _con(self):
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None); con.row_factory = sqlite3.Row; con.execute('PRAGMA busy_timeout=30000'); return con
    def _init_db(self):
        with self._con() as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS workflow_budget_runs(
              run_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, policy_json TEXT NOT NULL, started_at TEXT NOT NULL,
              deadline_at TEXT, reserved_concurrency INTEGER NOT NULL DEFAULT 0, completed_steps INTEGER NOT NULL DEFAULT 0,
              retry_count INTEGER NOT NULL DEFAULT 0, model_calls INTEGER NOT NULL DEFAULT 0, tool_calls INTEGER NOT NULL DEFAULT 0,
              input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0,
              confirmed_cost REAL NOT NULL DEFAULT 0, estimated_cost REAL NOT NULL DEFAULT 0,
              estimated_input_tokens INTEGER NOT NULL DEFAULT 0, usage_state TEXT NOT NULL DEFAULT 'unavailable',
              approval_waits INTEGER NOT NULL DEFAULT 0, cancellation_state TEXT, cancellation_deadline_at TEXT,
              stop_reason TEXT, released_at TEXT, decision_history_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_budget_workflow_reservation ON workflow_budget_runs(workflow_id,reserved_concurrency,released_at);
            CREATE TABLE IF NOT EXISTS workflow_dispatches(
              dispatch_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_index INTEGER NOT NULL, attempt INTEGER NOT NULL,
              phase TEXT NOT NULL, dispatch_type TEXT NOT NULL, action_identity TEXT NOT NULL, ordinal INTEGER NOT NULL,
              status TEXT NOT NULL, uncertainty TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(run_id,step_index,attempt,phase,dispatch_type,action_identity,ordinal));
            CREATE INDEX IF NOT EXISTS idx_dispatch_run ON workflow_dispatches(run_id,created_at);''')
            cols = {r['name'] for r in con.execute('PRAGMA table_info(workflow_budget_runs)')}
            if 'estimated_input_tokens' not in cols:
                con.execute('ALTER TABLE workflow_budget_runs ADD COLUMN estimated_input_tokens INTEGER NOT NULL DEFAULT 0')
    def _recover_uncertain_dispatches(self):
        """Fence dispatches whose process died before a durable outcome was recorded."""
        stamp = _now()
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            rows = con.execute("SELECT dispatch_id,run_id FROM workflow_dispatches WHERE status='dispatching'").fetchall()
            if rows:
                con.executemany(
                    "UPDATE workflow_dispatches SET status='uncertain',uncertainty='runtime_restart_before_dispatch_completion',updated_at=? WHERE dispatch_id=?",
                    [(stamp, row['dispatch_id']) for row in rows],
                )
                for run_id in sorted({row['run_id'] for row in rows}):
                    row = con.execute('SELECT decision_history_json FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone()
                    if not row:
                        continue
                    hist = json.loads(row['decision_history_json'] or '[]')
                    hist.append({'at':stamp,'decision':'recovery_required','reason':'uncertain dispatch recovered after runtime restart'})
                    con.execute(
                        "UPDATE workflow_budget_runs SET stop_reason=?,reserved_concurrency=0,released_at=COALESCE(released_at,?),decision_history_json=?,updated_at=? WHERE run_id=?",
                        ('Uncertain dispatch after runtime restart; verification/recovery required',stamp,json.dumps(hist),stamp,run_id),
                    )
            con.commit()

    @staticmethod
    def _deadline(policy, started):
        end = started + int(policy['max_runtime_seconds'])
        if policy.get('execution_deadline'):
            end = min(end, datetime.fromisoformat(str(policy['execution_deadline']).replace('Z','+00:00')).timestamp())
        return datetime.fromtimestamp(end, timezone.utc).isoformat()
    def reserve_run(self, run_id, workflow_id, policy):
        policy = normalize_policy(policy)
        if bool(getattr(getattr(self,'_tools',None),'emergency_stop',False)):
            raise WorkflowBudgetError('Emergency Stop active', code='workflow_emergency_stop', user_message='Emergency Stop active')
        stamp = _now(); deadline = self._deadline(policy, _ts())
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT 1 FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone(): con.rollback(); return
            active = con.execute("SELECT COUNT(*) c FROM workflow_budget_runs WHERE workflow_id=? AND reserved_concurrency=1 AND released_at IS NULL",(workflow_id,)).fetchone()['c']
            if active >= int(policy['max_concurrent_runs']):
                hist=[{'at':stamp,'decision':'deny','reason':'Concurrent run limit reached'}]
                con.execute("INSERT INTO workflow_budget_runs(run_id,workflow_id,policy_json,started_at,deadline_at,reserved_concurrency,stop_reason,decision_history_json,updated_at) VALUES(?,?,?,?,?,0,?,?,?)",(run_id,workflow_id,json.dumps(policy),stamp,deadline,'Concurrent run limit reached',json.dumps(hist),stamp)); con.commit()
                raise WorkflowBudgetError('Concurrent run limit reached',code='workflow_concurrency_limit',user_message='Concurrent run limit reached')
            hist=[{'at':stamp,'decision':'allow','reason':'concurrency slot reserved'}]
            con.execute("INSERT INTO workflow_budget_runs(run_id,workflow_id,policy_json,started_at,deadline_at,reserved_concurrency,decision_history_json,updated_at) VALUES(?,?,?,?,?,1,?,?)",(run_id,workflow_id,json.dumps(policy),stamp,deadline,json.dumps(hist),stamp)); con.commit()
        self._event('workflow.budget.decision',run_id=run_id,decision='allow',reason='concurrency slot reserved')
    def reacquire(self, run_id):
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT * FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone()
            if not row: con.rollback(); raise KeyError('workflow budget run not found')
            if row['reserved_concurrency'] and row['released_at'] is None: con.rollback(); return
            policy=json.loads(row['policy_json'])
            if row['stop_reason']=='Emergency Stop active' and not bool(getattr(getattr(self,'_tools',None),'emergency_stop',False)):
                con.execute('UPDATE workflow_budget_runs SET stop_reason=NULL,updated_at=? WHERE run_id=?',(_now(),run_id))
            active=con.execute("SELECT COUNT(*) c FROM workflow_budget_runs WHERE workflow_id=? AND reserved_concurrency=1 AND released_at IS NULL AND run_id<>?",(row['workflow_id'],run_id)).fetchone()['c']
            if active >= int(policy['max_concurrent_runs']): con.rollback(); raise WorkflowBudgetError('Concurrent run limit reached',code='workflow_concurrency_limit',user_message='Concurrent run limit reached')
            con.execute('UPDATE workflow_budget_runs SET reserved_concurrency=1,released_at=NULL,updated_at=? WHERE run_id=?',(_now(),run_id)); con.commit()
    def release(self, run_id, *, reason=None):
        stamp=_now()
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT decision_history_json FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone()
            if not row: con.rollback(); return
            hist=json.loads(row['decision_history_json'] or '[]'); hist.append({'at':stamp,'decision':'release','reason':reason or 'run no longer active'})
            con.execute('UPDATE workflow_budget_runs SET reserved_concurrency=0,released_at=?,decision_history_json=?,updated_at=? WHERE run_id=?',(stamp,json.dumps(hist),stamp,run_id)); con.commit()
    def mark_approval_wait(self, run_id):
        with self._con() as con: con.execute('BEGIN IMMEDIATE'); con.execute('UPDATE workflow_budget_runs SET approval_waits=approval_waits+1,updated_at=? WHERE run_id=?',(_now(),run_id)); con.commit()
        self._record_decision(run_id,'allow','waiting for trusted-action approval')
    def mark_stopped(self, run_id, reason):
        stamp=_now()
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT decision_history_json FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone()
            if not row: con.rollback(); raise KeyError('workflow budget run not found')
            hist=json.loads(row['decision_history_json'] or '[]'); hist.append({'at':stamp,'decision':'stop','reason':str(reason)[:240]})
            con.execute('UPDATE workflow_budget_runs SET stop_reason=?,decision_history_json=?,updated_at=? WHERE run_id=?',(str(reason)[:240],json.dumps(hist),stamp,run_id)); con.commit()
        self.release(run_id,reason=reason)
    def mark_cancelled(self, run_id, reason='Cancelled by owner'):
        status=self.status(run_id); deadline=datetime.fromtimestamp(_ts()+int(status['policy']['cancellation_grace_seconds']),timezone.utc).isoformat()
        with self._con() as con: con.execute('BEGIN IMMEDIATE'); con.execute('UPDATE workflow_budget_runs SET cancellation_state=?,cancellation_deadline_at=?,stop_reason=?,updated_at=? WHERE run_id=?',('cancelled',deadline,reason,_now(),run_id)); con.commit()
        self.release(run_id,reason=reason)
    def ensure_record(self, run_id, workflow_id, policy, *, released=True):
        policy=normalize_policy(policy); stamp=_now(); deadline=self._deadline(policy,_ts())
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            if not con.execute('SELECT 1 FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone():
                con.execute("INSERT INTO workflow_budget_runs(run_id,workflow_id,policy_json,started_at,deadline_at,reserved_concurrency,released_at,decision_history_json,updated_at) VALUES(?,?,?,?,?,?,?, ?,?)",(run_id,workflow_id,json.dumps(policy),stamp,deadline,0,stamp if released else None,json.dumps([{'at':stamp,'decision':'migrate','reason':'additive workflow budget migration'}]),stamp))
            con.commit()
    def apply_owner_override(self, run_id, updates):
        status=self.status(run_id)
        if not status['policy'].get('owner_override_allowed'): raise PermissionError('owner override is disabled for this workflow')
        allowed={k:v for k,v in dict(updates or {}).items() if k in DEFAULT_POLICY and k!='owner_override_allowed'}
        if not allowed: raise ValueError('no supported workflow budget fields supplied')
        policy=dict(status['policy']); policy.update(allowed); policy=normalize_policy(policy); stamp=_now()
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT decision_history_json FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone(); hist=json.loads(row['decision_history_json'] or '[]'); hist.append({'at':stamp,'decision':'owner_override','fields':sorted(allowed)})
            con.execute('UPDATE workflow_budget_runs SET policy_json=?,stop_reason=NULL,decision_history_json=?,updated_at=? WHERE run_id=?',(json.dumps(policy),json.dumps(hist),stamp,run_id)); con.commit()
        return self.status(run_id)
    def increment_completed_steps(self, run_id):
        with self._con() as con: con.execute('BEGIN IMMEDIATE'); con.execute('UPDATE workflow_budget_runs SET completed_steps=completed_steps+1,updated_at=? WHERE run_id=?',(_now(),run_id)); con.commit()
    def increment_retry(self, run_id):
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT retry_count,policy_json FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone()
            if not row: con.rollback(); raise KeyError('workflow budget run not found')
            if int(row['retry_count'])+1 > int(json.loads(row['policy_json'])['max_retries']): con.rollback(); self._deny(run_id,'Retry limit reached')
            con.execute('UPDATE workflow_budget_runs SET retry_count=retry_count+1,updated_at=? WHERE run_id=?',(_now(),run_id)); con.commit()
        self._record_decision(run_id,'allow','workflow retry reserved')
    def check(self, run_id, *, next_step=None, phase='step'):
        status=self.status(run_id); policy=status['policy']
        if status.get('stop_reason'): raise WorkflowBudgetError(status['stop_reason'])
        if self._emergency_active(): raise WorkflowBudgetError('Emergency Stop active',code='workflow_emergency_stop',user_message='Emergency Stop active')
        if status.get('deadline') and _ts() >= datetime.fromisoformat(status['deadline'].replace('Z','+00:00')).timestamp(): self._deny(run_id,'Maximum runtime reached')
        if next_step is not None and next_step >= int(policy['max_steps']): self._deny(run_id,'Workflow limit reached: maximum steps')
        if any(policy.get(k) is not None for k in ('max_output_tokens','max_total_tokens','max_cost')) and status['usage_state']=='unavailable':
            raise WorkflowBudgetError('Token/cost budget unavailable',code='workflow_usage_unavailable',user_message='Token/cost budget unavailable')
        self._record_decision(run_id,'allow',f'{phase} budget check',next_step=next_step); return status
    def _emergency_active(self): return bool(getattr(getattr(self,'_tools',None),'emergency_stop',False))
    def _deny(self, run_id, reason):
        stamp=_now()
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT decision_history_json FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone()
            if row:
                hist=json.loads(row['decision_history_json'] or '[]'); hist.append({'at':stamp,'decision':'deny','reason':reason}); con.execute('UPDATE workflow_budget_runs SET stop_reason=?,decision_history_json=?,updated_at=? WHERE run_id=?',(reason,json.dumps(hist),stamp,run_id))
            con.commit()
        self._event('workflow.budget.denied',run_id=run_id,reason=reason); raise WorkflowBudgetError(reason)
    def _record_decision(self, run_id, decision, reason, **details):
        stamp=_now(); safe={str(k):v for k,v in details.items() if k in {'next_step','dispatch_type','phase','attempt','limit'}}
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT decision_history_json FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone()
            if not row: con.rollback(); return
            hist=json.loads(row['decision_history_json'] or '[]'); hist.append({'at':stamp,'decision':str(decision)[:32],'reason':str(reason)[:240],**safe}); con.execute('UPDATE workflow_budget_runs SET decision_history_json=?,updated_at=? WHERE run_id=?',(json.dumps(hist),stamp,run_id)); con.commit()
        self._event('workflow.budget.decision',run_id=run_id,decision=str(decision)[:32],reason=str(reason)[:240],**safe)
    def _event(self,event,**payload):
        if self.events: self.events.emit(event,**payload)
        if self.audit: self.audit('workflow-budget',event.removeprefix('workflow.'),payload)
    def enter(self, run_id, step_index, attempt, phase='step'):
        manager=self
        class Scope:
            def __enter__(self): self.token=_ACTIVE.set(BudgetContext(manager,run_id,int(step_index),int(attempt),phase,{})); return current_budget_context()
            def __exit__(self,*_): _ACTIVE.reset(self.token)
        return Scope()
    def call_in_context(self,run_id,step_index,attempt,phase,fn,*args,**kwargs):
        with self.enter(run_id,step_index,attempt,phase): return fn(*args,**kwargs)
    @staticmethod
    def _dispatch_key(ctx, kind, identity):
        base=f'{kind}:{identity}'; ordinal=ctx.ordinals.get(base,0)+1; ctx.ordinals[base]=ordinal
        return hashlib.sha256(f'{ctx.run_id}|{ctx.step_index}|{ctx.attempt}|{ctx.phase}|{kind}|{identity}|{ordinal}'.encode()).hexdigest(),ordinal
    def begin_dispatch(self,kind,identity):
        ctx=current_budget_context()
        if ctx is None or ctx.manager is not self: return None
        self.check(ctx.run_id,next_step=ctx.step_index,phase=ctx.phase); dispatch_id,ordinal=self._dispatch_key(ctx,kind,identity); counter='model_calls' if kind=='model' else 'tool_calls'; limit='max_model_calls' if kind=='model' else 'max_tool_calls'; stamp=_now()
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); prior=con.execute('SELECT status FROM workflow_dispatches WHERE dispatch_id=?',(dispatch_id,)).fetchone()
            if prior: con.rollback(); raise WorkflowRecoveryRequired(f'duplicate {kind} dispatch blocked; prior state={prior["status"]}')
            row=con.execute(f'SELECT {counter},policy_json FROM workflow_budget_runs WHERE run_id=?',(ctx.run_id,)).fetchone()
            if not row: con.rollback(); raise WorkflowRecoveryRequired('workflow budget record is missing')
            if int(row[counter]) >= int(json.loads(row['policy_json'])[limit]): con.rollback(); self._deny(ctx.run_id,'Model-call limit reached' if kind=='model' else 'Tool-call limit reached')
            con.execute('INSERT INTO workflow_dispatches(dispatch_id,run_id,step_index,attempt,phase,dispatch_type,action_identity,ordinal,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(dispatch_id,ctx.run_id,ctx.step_index,ctx.attempt,ctx.phase,kind,identity,ordinal,'dispatching',stamp,stamp)); con.execute(f'UPDATE workflow_budget_runs SET {counter}={counter}+1,updated_at=? WHERE run_id=?',(stamp,ctx.run_id)); con.commit()
        self._record_decision(ctx.run_id,'allow',f'{kind} dispatch reserved',dispatch_type=kind,phase=ctx.phase,attempt=ctx.attempt); return dispatch_id
    def finish_dispatch(self,dispatch_id,*,status='completed',uncertainty=None):
        if not dispatch_id: return
        with self._con() as con: con.execute('BEGIN IMMEDIATE'); con.execute('UPDATE workflow_dispatches SET status=?,uncertainty=?,updated_at=? WHERE dispatch_id=?',(status,uncertainty,_now(),dispatch_id)); con.commit()
    def reconcile_uncertain_dispatch(self, run_id, dispatch_id, *, resolution):
        """Clear the workflow fence only from an externally verified recovery outcome."""
        allowed={'verified_effect','verified_no_effect'}
        if resolution not in allowed: raise WorkflowRecoveryRequired('workflow recovery outcome is not eligible for reconciliation')
        stamp=_now()
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute("SELECT status FROM workflow_dispatches WHERE dispatch_id=? AND run_id=?",(dispatch_id,run_id)).fetchone()
            if not row: con.rollback(); raise KeyError('workflow dispatch not found')
            if row['status'] not in {'uncertain','reconciled_effect','verified_no_effect'}: con.rollback(); raise WorkflowRecoveryRequired('workflow dispatch is not awaiting recovery')
            new_status='reconciled_effect' if resolution=='verified_effect' else 'verified_no_effect'
            con.execute("UPDATE workflow_dispatches SET status=?,uncertainty=NULL,updated_at=? WHERE dispatch_id=?",(new_status,stamp,dispatch_id))
            remaining=con.execute("SELECT COUNT(*) c FROM workflow_dispatches WHERE run_id=? AND status='uncertain'",(run_id,)).fetchone()['c']
            if not remaining:
                con.execute("UPDATE workflow_budget_runs SET stop_reason=NULL,updated_at=? WHERE run_id=?",(stamp,run_id))
            con.commit()
        self._record_decision(run_id,'recovery_reconciled',resolution,dispatch_type='recovery')
        return self.status(run_id)

    def record_input_estimate(self,payload):
        ctx=current_budget_context()
        if ctx is None or ctx.manager is not self: return 0
        try: encoded=json.dumps(payload or {},ensure_ascii=False,separators=(',',':'),default=str)
        except Exception: encoded=str(payload or '')
        estimate=max(1,(len(encoded.encode('utf-8'))+3)//4)
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); row=con.execute('SELECT estimated_input_tokens,input_tokens,policy_json FROM workflow_budget_runs WHERE run_id=?',(ctx.run_id,)).fetchone()
            if not row: con.rollback(); raise WorkflowRecoveryRequired('workflow budget record is missing')
            nxt=int(row['estimated_input_tokens'])+estimate; lim=json.loads(row['policy_json']).get('max_input_tokens')
            if lim is not None and max(int(row['input_tokens']),nxt)>int(lim): con.rollback(); self._deny(ctx.run_id,'Input-token limit reached')
            con.execute("UPDATE workflow_budget_runs SET estimated_input_tokens=?,usage_state=CASE WHEN usage_state='confirmed' THEN usage_state ELSE 'estimated' END,updated_at=? WHERE run_id=?",(nxt,_now(),ctx.run_id)); con.commit()
        self._event('workflow.budget.estimate',run_id=ctx.run_id,kind='input_tokens',amount=estimate,confirmed=False); return estimate
    def record_provider_usage(self,payload:Any):
        ctx=current_budget_context()
        if ctx is None or ctx.manager is not self or not isinstance(payload,dict): return
        usage=payload.get('usage') or payload.get('usage_metadata') or payload.get('usageMetadata')
        if not isinstance(usage,dict): return
        raw={'input_tokens':usage.get('prompt_tokens',usage.get('input_tokens',usage.get('promptTokenCount'))),'output_tokens':usage.get('completion_tokens',usage.get('output_tokens',usage.get('candidatesTokenCount'))),'total_tokens':usage.get('total_tokens',usage.get('totalTokenCount')),'confirmed_cost':usage.get('cost',usage.get('total_cost'))}; vals={}
        try:
            for k,v in raw.items():
                if v is not None: vals[k]=max(0.0,float(v)) if k=='confirmed_cost' else max(0,int(v))
            if 'total_tokens' not in vals and ('input_tokens' in vals or 'output_tokens' in vals): vals['total_tokens']=vals.get('input_tokens',0)+vals.get('output_tokens',0)
        except (TypeError,ValueError): return
        if not vals: return
        with self._con() as con:
            con.execute('BEGIN IMMEDIATE'); assigns=[]; params=[]
            for k,v in vals.items(): assigns.append(f'{k}={k}+?'); params.append(v)
            assigns += ["usage_state='confirmed'",'updated_at=?']; params += [_now(),ctx.run_id]; con.execute(f'UPDATE workflow_budget_runs SET {",".join(assigns)} WHERE run_id=?',params); con.commit()
        self._enforce_usage(ctx.run_id)
    def _enforce_usage(self,run_id):
        s=self.status(run_id); p=s['policy']
        for key,used,reason in [('max_input_tokens',s['consumption']['input_tokens'],'Input-token limit reached'),('max_output_tokens',s['consumption']['output_tokens'],'Output-token limit reached'),('max_total_tokens',s['consumption']['total_tokens'],'Token limit reached'),('max_cost',s['consumption']['confirmed_cost'],'Cost limit reached')]:
            if p.get(key) is not None and used>p[key]: self._deny(run_id,reason)
    def install_runtime_guards(self,executor):
        if executor is None: return
        tools=getattr(executor,'tools',None); models=getattr(executor,'models',None); self._tools=tools
        with self._install_lock:
            if tools is not None and not getattr(tools,'_workflow_budget_guard_installed',False):
                manager=self; original_register=tools.register
                if hasattr(tools,'set_emergency_stop'):
                    original_stop=tools.set_emergency_stop
                    def guarded_stop(enabled):
                        value=original_stop(enabled); cb=getattr(manager,'on_emergency_stop',None)
                        if enabled and callable(cb): cb()
                        return value
                    tools.set_emergency_stop=guarded_stop
                def wrap_tool(tool):
                    if getattr(tool.handler,'_workflow_budget_wrapped',False): return tool
                    original=tool.handler
                    def handler(params,_tool=tool,_handler=original):
                        identity=f'{_tool.name}:{hashlib.sha256(json.dumps(params or {},sort_keys=True,default=str).encode()).hexdigest()}'; did=manager.begin_dispatch('tool',identity)
                        try: result=_handler(params)
                        except Exception as exc: manager.finish_dispatch(did,status='uncertain' if int(_tool.risk)>=2 else 'failed',uncertainty=type(exc).__name__); raise
                        manager.finish_dispatch(did); return result
                    handler._workflow_budget_wrapped=True; tool.handler=handler; return tool
                def guarded_register(tool): return original_register(wrap_tool(tool))
                tools.register=guarded_register
                if hasattr(tools,'authorize') and hasattr(tools,'effective_risk'):
                    original_authorize=tools.authorize
                    def guarded_authorize(tool,confirmed=False,*,parameters=None,data_classification='internal'):
                        decision=original_authorize(tool,confirmed=confirmed,parameters=parameters,data_classification=data_classification); ctx=current_budget_context()
                        if ctx is None or ctx.manager is not manager or confirmed or not decision.allowed: return decision
                        threshold={'read_only':0,'reversible':1,'consequential':2,'destructive':3,'critical':4}[manager.status(ctx.run_id)['policy']['approval_threshold']]; risk=int(tools.effective_risk(tool,parameters=parameters,data_classification=data_classification))
                        return type(decision)(False,True,'workflow policy requires approval') if risk>=threshold else decision
                    tools.authorize=guarded_authorize
                for t in list(tools.all()): wrap_tool(t)
                tools._workflow_budget_guard_installed=True
            if models is not None and hasattr(models,'_request') and not getattr(models,'_workflow_budget_guard_installed',False):
                manager=self; original=models._request
                def guarded_request(provider,method,path,*args,**kwargs):
                    identity=f'{getattr(provider,"id","unknown")}:{method}:{path}'; manager.record_input_estimate(kwargs.get('json') if 'json' in kwargs else kwargs.get('data')); did=manager.begin_dispatch('model',identity)
                    try: response=original(provider,method,path,*args,**kwargs)
                    except Exception as exc: manager.finish_dispatch(did,status='uncertain',uncertainty=type(exc).__name__); raise
                    manager.finish_dispatch(did)
                    try: manager.record_provider_usage(response.json())
                    except Exception: pass
                    return response
                models._request=guarded_request; models._workflow_budget_guard_installed=True
    def _position(self,run_id,wid,started,active):
        if not active: return None
        with self._con() as con: return int(con.execute("SELECT COUNT(*) c FROM workflow_budget_runs WHERE workflow_id=? AND reserved_concurrency=1 AND released_at IS NULL AND (started_at<? OR (started_at=? AND run_id<=?))",(wid,started,started,run_id)).fetchone()['c'])
    def status(self,run_id):
        with self._con() as con:
            row=con.execute('SELECT * FROM workflow_budget_runs WHERE run_id=?',(run_id,)).fetchone()
            if not row: raise KeyError('workflow budget run not found')
            dispatch=[dict(r) for r in con.execute('SELECT dispatch_id,step_index,attempt,phase,dispatch_type,action_identity,status,uncertainty,created_at,updated_at FROM workflow_dispatches WHERE run_id=? ORDER BY created_at',(run_id,))]
        item=dict(row); p=json.loads(item.pop('policy_json')); history=json.loads(item.pop('decision_history_json') or '[]'); keys=('completed_steps','retry_count','model_calls','tool_calls','input_tokens','output_tokens','total_tokens','confirmed_cost','estimated_cost','estimated_input_tokens','approval_waits'); consumption={k:item[k] for k in keys}
        remaining={'steps':max(0,int(p['max_steps'])-item['completed_steps']),'retries':max(0,int(p['max_retries'])-item['retry_count']),'model_calls':max(0,int(p['max_model_calls'])-item['model_calls']),'tool_calls':max(0,int(p['max_tool_calls'])-item['tool_calls'])}
        for k,f in [('input_tokens','max_input_tokens'),('output_tokens','max_output_tokens'),('total_tokens','max_total_tokens')]: remaining[k]=None if p.get(f) is None else max(0,int(p[f])-item[k])
        remaining['cost']=None if p.get('max_cost') is None else max(0.0,float(p['max_cost'])-item['confirmed_cost']); active=bool(item['reserved_concurrency'] and item['released_at'] is None)
        return {'run_id':run_id,'workflow_id':item['workflow_id'],'policy':p,'started_at':item['started_at'],'deadline':item['deadline_at'],'reserved_concurrency':active,'released_at':item['released_at'],'consumption':consumption,'remaining':remaining,'usage_state':item['usage_state'],'confirmed_usage':item['usage_state']=='confirmed','estimated_usage':{'input_tokens':item['estimated_input_tokens'],'cost':item['estimated_cost'],'confirmed':False},'cancellation_state':item['cancellation_state'],'cancellation_deadline':item['cancellation_deadline_at'],'stop_reason':item['stop_reason'],'decision_history':history,'concurrency_position':self._position(run_id,item['workflow_id'],item['started_at'],active),'dispatches':dispatch}
