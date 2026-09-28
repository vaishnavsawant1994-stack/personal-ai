from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.executor import ConfirmationRequired, ExecutionCancelled
from automation.budget import DEFAULT_POLICY, WorkflowBudgetError, WorkflowBudgetManager, WorkflowRecoveryRequired, normalize_policy
from automation.conditions import evaluate_condition
from security.projection_redaction import sanitize_external_value, sanitize_sensitive_text
from desktop.operator_transactions import OperatorBinding, OperatorTransactionStore
from desktop.operator_transactions import OperatorBinding, OperatorTransactionStore


def now():
    return datetime.now(timezone.utc).isoformat()


def now_ts():
    return datetime.now(timezone.utc).timestamp()


class AutomationEngine:
    RUN_UPDATE_FIELDS = frozenset({
        'status', 'context_json', 'current_step', 'completed_steps_json', 'result_json',
        'error', 'pending_approval_id', 'updated_at', 'completed_at',
        'recovery_transaction_id', 'recovery_source_dispatch_id',
        'recovery_consumed_verification_id',
    })
    """Scheduled automations plus durable, bounded multi-step workflows."""

    TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted', 'budget_exceeded'}

    def __init__(self, path: Path, executor=None, events=None, poll_seconds: float = 2.0,
                 context_provider=None, default_timeout_seconds: int = 120, default_retries: int = 2):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = executor; self.events = events; self.poll_seconds = poll_seconds
        self.context_provider = context_provider or (lambda: {})
        self.default_timeout_seconds = max(1, int(default_timeout_seconds))
        self.default_retries = max(0, int(default_retries))
        self._stop = threading.Event(); self._thread = None
        self._workflow_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='personal-ai-workflow')
        self._step_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='personal-ai-workflow-step')
        self._run_locks: dict[str, threading.Lock] = {}; self._run_cancel_events: dict[str, threading.Event] = {}
        self._init_db()
        audit = getattr(getattr(executor, 'memory', None), 'audit', None)
        self.budgets = WorkflowBudgetManager(self.path.with_name('workflow-budgets.sqlite3'), events=events, audit=audit)
        self.budgets.on_emergency_stop = self._halt_for_emergency_stop
        self.budgets.install_runtime_guards(executor)
        self._migrate_budget_records(); self._recover_interrupted_runs()
        if self.events: self.events.subscribe('automation.trigger', self._on_trigger_event)

    def _con(self):
        con = sqlite3.connect(self.path, timeout=30); con.row_factory = sqlite3.Row; return con

    def _init_db(self):
        with self._con() as con:
            con.execute('CREATE TABLE IF NOT EXISTS automations(id TEXT PRIMARY KEY,title TEXT,prompt TEXT,next_run_at TEXT,interval_seconds INTEGER,enabled INTEGER,last_run_at TEXT,created_at TEXT)')
            cols={r['name'] for r in con.execute('PRAGMA table_info(automations)')}
            if 'condition_json' not in cols: con.execute("ALTER TABLE automations ADD COLUMN condition_json TEXT DEFAULT '{}'")
            if 'last_result_json' not in cols: con.execute('ALTER TABLE automations ADD COLUMN last_result_json TEXT')
            con.execute('''CREATE TABLE IF NOT EXISTS workflows(
                id TEXT PRIMARY KEY,title TEXT NOT NULL,trigger_json TEXT NOT NULL,steps_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,paused INTEGER NOT NULL DEFAULT 0,next_run_at TEXT,
                interval_seconds INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_run_at TEXT)''')
            workflow_cols={r['name'] for r in con.execute('PRAGMA table_info(workflows)')}
            if 'policy_json' not in workflow_cols: con.execute("ALTER TABLE workflows ADD COLUMN policy_json TEXT NOT NULL DEFAULT '{}'")
            con.execute('''CREATE TABLE IF NOT EXISTS workflow_runs(
                id TEXT PRIMARY KEY,workflow_id TEXT NOT NULL,status TEXT NOT NULL,trigger_json TEXT,context_json TEXT,
                current_step INTEGER NOT NULL DEFAULT 0,completed_steps_json TEXT NOT NULL DEFAULT '[]',result_json TEXT,
                error TEXT,pending_approval_id TEXT,started_at TEXT NOT NULL,updated_at TEXT NOT NULL,completed_at TEXT,
                FOREIGN KEY(workflow_id) REFERENCES workflows(id))''')
            run_cols={r['name'] for r in con.execute('PRAGMA table_info(workflow_runs)')}
            additions={'owner_id':'TEXT','device_id':'TEXT','session_id':'TEXT','reauthenticated_at':'REAL','idempotency_key':'TEXT'}
            for name,definition in additions.items():
                if name not in run_cols: con.execute(f'ALTER TABLE workflow_runs ADD COLUMN {name} {definition}')
            con.execute('CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow ON workflow_runs(workflow_id,started_at)')
            con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_runs_idempotency ON workflow_runs(workflow_id,idempotency_key) WHERE idempotency_key IS NOT NULL')
            for name,definition in {'recovery_transaction_id':'TEXT','recovery_source_dispatch_id':'TEXT','recovery_consumed_verification_id':'TEXT'}.items():
                if name not in run_cols: con.execute(f'ALTER TABLE workflow_runs ADD COLUMN {name} {definition}')

    def _halt_for_emergency_stop(self):
        with self._con() as con:
            rows=con.execute("SELECT id,workflow_id FROM workflow_runs WHERE status IN ('queued','running','rolling_back','waiting_approval')").fetchall()
            con.execute("UPDATE workflow_runs SET status='recovery_required',error='Emergency Stop active; owner review required before resume',pending_approval_id=NULL,updated_at=?,completed_at=NULL WHERE status IN ('queued','running','rolling_back','waiting_approval')",(now(),))
        for row in rows:
            event=self._run_cancel_events.get(row['id'])
            if event: event.set()
            try: self.budgets.mark_stopped(row['id'],'Emergency Stop active')
            except KeyError: pass
            self._emit('workflow.recovery_required',run_id=row['id'],workflow_id=row['workflow_id'],reason='Emergency Stop active')

    def _migrate_budget_records(self):
        with self._con() as con: rows=con.execute('SELECT id,workflow_id,status FROM workflow_runs').fetchall()
        for row in rows:
            try: policy=self.workflow(row['workflow_id'])['policy']
            except Exception: policy=dict(DEFAULT_POLICY)
            self.budgets.ensure_record(row['id'],row['workflow_id'],policy,released=row['status'] not in {'running','rolling_back','queued','waiting_approval'})

    def _recover_interrupted_runs(self):
        with self._con() as con:
            rows=con.execute("SELECT id FROM workflow_runs WHERE status IN ('running','rolling_back','queued')").fetchall()
            con.execute("UPDATE workflow_runs SET status='recovery_required',error='runtime restarted; owner review required before resuming current checkpoint',updated_at=?,completed_at=NULL WHERE status IN ('running','rolling_back','queued')",(now(),))
        for row in rows: self.budgets.release(row['id'], reason='Recovery review required')

    def create(self,title,prompt,next_run_at,interval_seconds=None,condition=None):
        aid=str(uuid.uuid4())
        with self._con() as con: con.execute('INSERT INTO automations(id,title,prompt,next_run_at,interval_seconds,enabled,last_run_at,created_at,condition_json) VALUES(?,?,?,?,?,1,NULL,?,?)',(aid,title,prompt,next_run_at,interval_seconds,now(),json.dumps(condition or {})))
        return aid
    def list(self):
        with self._con() as con: return [dict(r) for r in con.execute('SELECT * FROM automations ORDER BY created_at DESC')]
    def enable(self,automation_id,enabled=True):
        with self._con() as con: con.execute('UPDATE automations SET enabled=? WHERE id=?',(int(enabled),automation_id))

    def create_workflow(self,title:str,trigger:dict,steps:list[dict],*,next_run_at=None,interval_seconds=None,policy:dict|None=None):
        trigger=dict(trigger or {}); embedded_policy=trigger.pop('policy',None); policy=normalize_policy(policy if policy is not None else embedded_policy); t=str(trigger.get('type','event'))
        if t not in {'event','schedule','manual'}: raise ValueError('workflow trigger type must be event, schedule or manual')
        if not steps: raise ValueError('workflow requires at least one step')
        normalized=[self._normalize_step(step,i) for i,step in enumerate(steps)]
        if len(normalized)>50: raise ValueError('workflow may contain at most 50 steps')
        if len(normalized)>int(policy['max_steps']): raise ValueError('workflow steps exceed configured max_steps')
        if t=='schedule' and not next_run_at:
            next_run_at=str(trigger.get('next_run_at') or '')
            if not next_run_at: raise ValueError('scheduled workflow requires next_run_at')
        wid=str(uuid.uuid4()); stamp=now()
        with self._con() as con: con.execute('''INSERT INTO workflows(id,title,trigger_json,steps_json,enabled,paused,next_run_at,interval_seconds,created_at,updated_at,last_run_at,policy_json) VALUES(?,?,?,?,1,0,?,?,?,?,NULL,?)''',(wid,str(title),json.dumps(trigger),json.dumps(normalized),next_run_at,interval_seconds,stamp,stamp,json.dumps(policy)))
        self._emit('workflow.created',workflow_id=wid,title=title); return wid

    def _normalize_step(self,step,position):
        row=dict(step or {}); kind=str(row.get('kind','prompt')).strip().lower()
        if kind not in {'prompt','condition','set','emit'}: raise ValueError(f'unsupported workflow step kind: {kind}')
        row['kind']=kind; row['position']=int(position); row['retries']=max(0,min(int(row.get('retries',self.default_retries)),10)); row['timeout_seconds']=max(1,min(int(row.get('timeout_seconds',self.default_timeout_seconds)),3600))
        if kind=='prompt' and not str(row.get('prompt','')).strip(): raise ValueError('prompt workflow step requires prompt')
        if kind=='condition' and not isinstance(row.get('condition'),dict): raise ValueError('condition workflow step requires condition object')
        if kind=='set' and not str(row.get('key','')).strip(): raise ValueError('set workflow step requires key')
        if kind=='emit' and not str(row.get('event','')).strip(): raise ValueError('emit workflow step requires event')
        return row

    def workflows(self):
        with self._con() as con: rows=[dict(r) for r in con.execute('SELECT * FROM workflows ORDER BY created_at DESC')]
        for r in rows: r['trigger']=json.loads(r.pop('trigger_json') or '{}'); r['steps']=json.loads(r.pop('steps_json') or '[]'); r['policy']=normalize_policy(json.loads(r.pop('policy_json') or '{}'))
        return rows
    def workflow(self,workflow_id):
        with self._con() as con: row=con.execute('SELECT * FROM workflows WHERE id=?',(workflow_id,)).fetchone()
        if not row: raise KeyError('workflow not found')
        d=dict(row); d['trigger']=json.loads(d.pop('trigger_json') or '{}'); d['steps']=json.loads(d.pop('steps_json') or '[]'); d['policy']=normalize_policy(json.loads(d.pop('policy_json') or '{}')); return d
    def pause_workflow(self,workflow_id,paused=True):
        with self._con() as con: cur=con.execute('UPDATE workflows SET paused=?,updated_at=? WHERE id=?',(int(paused),now(),workflow_id))
        if cur.rowcount!=1: raise KeyError('workflow not found')
        self._emit('workflow.paused' if paused else 'workflow.resumed',workflow_id=workflow_id); return {'workflow_id':workflow_id,'paused':bool(paused)}
    def enable_workflow(self,workflow_id,enabled=True):
        with self._con() as con: cur=con.execute('UPDATE workflows SET enabled=?,updated_at=? WHERE id=?',(int(enabled),now(),workflow_id))
        if cur.rowcount!=1: raise KeyError('workflow not found')
        return {'workflow_id':workflow_id,'enabled':bool(enabled)}

    def trigger(self,event_name,payload=None):
        payload=dict(payload or {}); matches=[]
        for wf in self.workflows():
            if not wf['enabled'] or wf['paused']: continue
            trig=wf['trigger']
            if trig.get('type','event')!='event' or str(trig.get('event'))!=str(event_name): continue
            cond=trig.get('condition') or {}; context={**(self.context_provider() or {}),'event':payload,'trigger':{'name':event_name}}
            if cond and not evaluate_condition(cond,context): continue
            try: matches.append(self.run_workflow(wf['id'],trigger_payload={'event':event_name,'payload':payload},context=context,background=True))
            except WorkflowBudgetError as exc: self._emit('workflow.skipped',workflow_id=wf['id'],reason=exc.user_message)
        return matches
    def _on_trigger_event(self,event):
        name=str(event.get('name') or event.get('trigger') or '')
        if name: self.trigger(name,dict(event.get('payload') or {}))

    def run_workflow(self,workflow_id,*,trigger_payload=None,context=None,background=False,owner_id=None,device_id=None,session_id=None,reauthenticated_at=None,idempotency_key=None):
        wf=self.workflow(workflow_id)
        if not wf['enabled']: raise RuntimeError('workflow is disabled')
        if wf['paused']: raise RuntimeError('workflow is paused')
        run_context={**(self.context_provider() or {}),**(context or {})}; key=idempotency_key or run_context.pop('idempotency_key',None)
        if key:
            key=str(key)[:160]
            with self._con() as con: existing=con.execute('SELECT id FROM workflow_runs WHERE workflow_id=? AND idempotency_key=?',(workflow_id,key)).fetchone()
            if existing: return existing['id']
        run_id=str(uuid.uuid4()); stamp=now()
        try: self.budgets.reserve_run(run_id,workflow_id,wf['policy'])
        except WorkflowBudgetError: self._emit('workflow.budget_exceeded',workflow_id=workflow_id,run_id=run_id,reason='Concurrent run limit reached'); raise
        try:
            with self._con() as con: con.execute('''INSERT INTO workflow_runs(id,workflow_id,status,trigger_json,context_json,current_step,completed_steps_json,result_json,error,pending_approval_id,started_at,updated_at,completed_at,owner_id,device_id,session_id,reauthenticated_at,idempotency_key) VALUES(?,?, 'queued', ?, ?, 0, '[]', NULL, NULL, NULL, ?, ?, NULL, ?, ?, ?, ?, ?)''',(run_id,workflow_id,json.dumps(trigger_payload or {}),json.dumps(run_context,default=str),stamp,stamp,owner_id,device_id,session_id,reauthenticated_at,key))
        except sqlite3.IntegrityError:
            self.budgets.release(run_id,reason='duplicate idempotent run request')
            with self._con() as con: existing=con.execute('SELECT id FROM workflow_runs WHERE workflow_id=? AND idempotency_key=?',(workflow_id,key)).fetchone()
            if existing: return existing['id']
            raise
        if background: self._workflow_pool.submit(self._continue_run,run_id)
        else: self._continue_run(run_id)
        return run_id

    def _budget_terminal(self,run_id,run,wf,exc):
        reason=exc.user_message if isinstance(exc,WorkflowBudgetError) else str(exc); self._update_run(run_id,status='budget_exceeded',error=reason,completed_at=now()); self.budgets.mark_stopped(run_id,reason); self._emit('workflow.budget_exceeded',run_id=run_id,workflow_id=wf['id'],reason=reason)

    def _continue_run(self,run_id,*,approved_result=None):
        lock=self._run_locks.setdefault(run_id,threading.Lock())
        if not lock.acquire(blocking=False): return
        try:
            run=self._run(run_id)
            if run['status'] in self.TERMINAL or run['status']=='recovery_required': return
            wf=self.workflow(run['workflow_id']); steps=wf['steps']; context=json.loads(run['context_json'] or '{}'); completed=json.loads(run['completed_steps_json'] or '[]'); index=int(run['current_step'])
            try: self.budgets.check(run_id,next_step=index)
            except WorkflowBudgetError as exc: self._budget_terminal(run_id,run,wf,exc); return
            if approved_result is not None: completed.append({'step':index,'kind':'approval_resume','result':approved_result}); index+=1; self.budgets.increment_completed_steps(run_id)
            self._update_run(run_id,status='running',current_step=index,completed_steps_json=json.dumps(completed),pending_approval_id=None); self._emit('workflow.started',run_id=run_id,workflow_id=wf['id'],title=wf['title'])
            while index<len(steps):
                current=self._run(run_id)
                if current['status'] in {'cancelled','recovery_required'}: return
                try: self.budgets.check(run_id,next_step=index)
                except WorkflowBudgetError as exc: self._budget_terminal(run_id,current,wf,exc); return
                step=steps[index]
                try: result=self._execute_workflow_step(run_id,index,step,context,run)
                except ExecutionCancelled:
                    if self._run(run_id)['status']=='recovery_required': return
                    self._update_run(run_id,status='cancelled',error='cancelled by owner',completed_at=now()); self.budgets.mark_cancelled(run_id); self._emit('workflow.cancelled',run_id=run_id,workflow_id=wf['id'],reason='owner_cancelled'); return
                except ConfirmationRequired as approval:
                    self.budgets.mark_approval_wait(run_id); self._update_run(run_id,status='waiting_approval',current_step=index,context_json=json.dumps(context,default=str),completed_steps_json=json.dumps(completed,default=str),pending_approval_id=approval.approval_id); self._emit('workflow.approval_required',run_id=run_id,workflow_id=wf['id'],approval_id=approval.approval_id,tool=approval.tool_name); return
                except WorkflowRecoveryRequired as exc:
                    self._update_run(run_id,status='recovery_required',error=exc.user_message,completed_at=None); self.budgets.release(run_id,reason=exc.user_message); self._emit('workflow.recovery_required',run_id=run_id,workflow_id=wf['id'],reason=exc.user_message); return
                except WorkflowBudgetError as exc: self._budget_terminal(run_id,self._run(run_id),wf,exc); return
                except Exception as exc:
                    rollback=self._rollback(wf,completed,context,run,run_id); safe_error=sanitize_sensitive_text(str(exc))[:1000]; self._update_run(run_id,status='failed',error=safe_error,context_json=json.dumps(context,default=str),completed_steps_json=json.dumps(completed,default=str),result_json=json.dumps({'rollback':rollback},default=str),completed_at=now()); self.budgets.release(run_id,reason='workflow failed'); self._emit('workflow.failed',run_id=run_id,workflow_id=wf['id'],error=safe_error,rollback=rollback); return
                if self._run(run_id)['status']=='cancelled': return
                completed.append({'step':index,'kind':step['kind'],'result':result}); context[f'step_{index+1}']=result; index+=1; self.budgets.increment_completed_steps(run_id); self._update_run(run_id,current_step=index,context_json=json.dumps(context,default=str),completed_steps_json=json.dumps(completed,default=str)); self._emit('workflow.step.completed',run_id=run_id,workflow_id=wf['id'],step=index,kind=step['kind'])
            result={'completed_steps':completed,'context':context}
            if self._run(run_id)['status']=='cancelled': return
            self._update_run(run_id,status='completed',result_json=json.dumps(result,default=str),completed_at=now()); self.budgets.release(run_id,reason='workflow completed')
            with self._con() as con: con.execute('UPDATE workflows SET last_run_at=?,updated_at=? WHERE id=?',(now(),now(),wf['id']))
            self._emit('workflow.completed',run_id=run_id,workflow_id=wf['id'],result=result)
        finally: lock.release()

    @staticmethod
    def _authority_kwargs(run): return {f:run.get(f) for f in ('owner_id','device_id','session_id','reauthenticated_at') if run.get(f) is not None}
    @staticmethod
    def _assert_authority(run,*,owner_id=None,device_id=None,session_id=None):
        for field,value in {'owner_id':owner_id,'device_id':device_id,'session_id':session_id}.items():
            expected=run.get(field)
            if expected is not None and value!=expected: raise PermissionError(f'workflow {field.removesuffix("_id")} identity mismatch')

    def _execute_workflow_step(self,run_id,index,step,context,run):
        kind=step['kind']
        if kind=='condition': return {'matched':evaluate_condition(step['condition'],context)}
        if kind=='set': context[str(step['key'])]=step.get('value'); return {'key':str(step['key']),'value':step.get('value')}
        if kind=='emit': payload=dict(step.get('payload') or {}); self._emit(str(step['event']),run_id=run_id,**payload); return {'emitted':str(step['event'])}
        if kind!='prompt': raise ValueError(f'unsupported workflow step kind: {kind}')
        if not self.executor: raise RuntimeError('workflow executor unavailable')
        prompt=self._render(str(step['prompt']),context); retries=int(step.get('retries',self.default_retries)); timeout=int(step.get('timeout_seconds',self.default_timeout_seconds)); last_error=None
        budget=self.budgets.status(run_id); remaining=max(0.05,datetime.fromisoformat(budget['deadline'].replace('Z','+00:00')).timestamp()-now_ts()); timeout=min(timeout,remaining)
        for attempt in range(retries+1):
            self.budgets.check(run_id,next_step=index)
            if attempt>0: self.budgets.increment_retry(run_id)
            cancel_event=threading.Event(); self._run_cancel_events[run_id]=cancel_event; future=self._step_pool.submit(self.budgets.call_in_context,run_id,index,attempt,'step',self.executor.chat,prompt,cancel_event=cancel_event,**self._authority_kwargs(run))
            try: reply=future.result(timeout=timeout); self._run_cancel_events.pop(run_id,None); return {'reply':reply,'attempt':attempt+1}
            except FutureTimeout: cancel_event.set(); last_error=WorkflowRecoveryRequired(f'workflow step timed out after {timeout}s; dispatch result may be unknown')
            except ConfirmationRequired: raise
            except ExecutionCancelled as exc:
                self._run_cancel_events.pop(run_id,None)
                if cancel_event.is_set() or self._run(run_id)['status']=='cancelled': raise
                last_error=exc
            except WorkflowBudgetError: raise
            except Exception as exc: last_error=exc
            if attempt<retries:
                if isinstance(last_error,WorkflowRecoveryRequired): raise last_error
                self._emit('workflow.step.retry',run_id=run_id,attempt=attempt+1,error=type(last_error).__name__); time.sleep(min(2**attempt,5))
            self._run_cancel_events.pop(run_id,None)
        raise RuntimeError(str(last_error or 'workflow step failed'))

    @staticmethod
    def _render(text,context):
        for key,value in context.items(): text=text.replace('{{'+str(key)+'}}',str(value))
        return text

    def approve_run(self,run_id,approval_id,*,owner_id=None,device_id=None,session_id=None,reauthenticated_at=None):
        run=self._run(run_id)
        self._assert_authority(run,owner_id=owner_id,device_id=device_id,session_id=session_id)
        if run['status']!='waiting_approval' or run['pending_approval_id']!=approval_id: raise PermissionError('run is not waiting for this approval')
        self.budgets.check(run_id,next_step=int(run['current_step'])); authority=self._authority_kwargs(run)
        if reauthenticated_at is not None: authority['reauthenticated_at']=reauthenticated_at
        with self.budgets.enter(run_id,int(run['current_step']),0,'approval_resume'): result=self.executor.approve(approval_id,**authority)
        self._update_run(run_id,status='queued',pending_approval_id=None); self._workflow_pool.submit(self._continue_run,run_id,approved_result=result); return {'run_id':run_id,'approval_id':approval_id,'resumed':True}
    def reject_run(self,run_id,approval_id,*,owner_id=None,device_id=None,session_id=None):
        run=self._run(run_id)
        self._assert_authority(run,owner_id=owner_id,device_id=device_id,session_id=session_id)
        if run['status']!='waiting_approval' or run['pending_approval_id']!=approval_id: raise PermissionError('run is not waiting for this approval')
        self.executor.reject(approval_id,**self._authority_kwargs(run)); self._update_run(run_id,status='cancelled',pending_approval_id=None,completed_at=now(),error='user rejected approval'); self.budgets.mark_cancelled(run_id,'Cancelled by owner'); self._emit('workflow.cancelled',run_id=run_id,workflow_id=run['workflow_id'],reason='approval_rejected'); return {'run_id':run_id,'cancelled':True}
    def cancel_run(self,run_id,*,owner_id=None,device_id=None,session_id=None):
        run=self._run(run_id); self._assert_authority(run,owner_id=owner_id,device_id=device_id,session_id=session_id)
        if run['status'] in self.TERMINAL: return {'run_id':run_id,'cancelled':run['status']=='cancelled','status':run['status']}
        cancel_event=self._run_cancel_events.get(run_id); self._update_run(run_id,status='cancelled',pending_approval_id=None,error='cancelled by owner',completed_at=now()); self.budgets.mark_cancelled(run_id)
        if cancel_event: cancel_event.set()
        if run['status']=='waiting_approval' and run.get('pending_approval_id') and self.executor:
            try: self.executor.reject(run['pending_approval_id'],**self._authority_kwargs(run))
            except Exception: pass
        self._emit('workflow.cancelled',run_id=run_id,workflow_id=run['workflow_id'],reason='owner_cancelled'); return {'run_id':run_id,'cancelled':True,'status':'cancelled'}

    def cancel_device_runs(self,device_id,*,reason='device_revoked'):
        device_id=str(device_id or '').strip()
        if not device_id:return 0
        with self._con() as con:
            rows=con.execute(
                "SELECT id,owner_id,device_id,session_id FROM workflow_runs WHERE device_id=? AND status NOT IN ('completed','failed','cancelled','interrupted','budget_exceeded')",
                (device_id,),
            ).fetchall()
        cancelled=0
        for row in rows:
            result=self.cancel_run(
                row['id'],owner_id=row['owner_id'],device_id=row['device_id'],session_id=row['session_id'],
            )
            if result.get('cancelled'):
                cancelled+=1
                self._update_run(row['id'],error=str(reason)[:160])
        return cancelled

    def cancel_session_runs(self,session_id,*,reason='session_revoked'):
        session_id=str(session_id or '').strip()
        if not session_id:return 0
        with self._con() as con:
            rows=con.execute(
                "SELECT id,owner_id,device_id,session_id FROM workflow_runs WHERE session_id=? AND status NOT IN ('completed','failed','cancelled','interrupted','budget_exceeded')",
                (session_id,),
            ).fetchall()
        cancelled=0
        for row in rows:
            result=self.cancel_run(
                row['id'],owner_id=row['owner_id'],device_id=row['device_id'],session_id=row['session_id'],
            )
            if result.get('cancelled'):
                cancelled+=1
                self._update_run(row['id'],error=str(reason)[:160])
        return cancelled
    def _recovery_authority(self):
        tools=getattr(self.executor,'tools',None)
        getter=getattr(tools,'ensure_recovery_authority',None) if tools is not None else None
        if not callable(getter): raise RuntimeError('W7 recovery authority is unavailable')
        return getter(),tools

    def link_recovery(self,run_id,*,owner_id=None,device_id=None,session_id=None):
        run=self._run(run_id); self._assert_authority(run,owner_id=owner_id,device_id=device_id,session_id=session_id)
        if run['status']!='recovery_required': raise RuntimeError('workflow run is not waiting for recovery')
        budget=self.budgets.status(run_id); uncertain=[d for d in budget['dispatches'] if d['status']=='uncertain']
        if not uncertain: raise RuntimeError('workflow has no uncertain dispatch to reconcile')
        if len(uncertain)!=1: raise RuntimeError('workflow has multiple uncertain dispatches; manual recovery review required')
        source=uncertain[0]; authority,tools=self._recovery_authority(); txid=str(run.get('recovery_transaction_id') or uuid.uuid5(uuid.NAMESPACE_URL,f'personal-ai:workflow-recovery:{run_id}:{source["dispatch_id"]}'))
        store=OperatorTransactionStore(authority.path); epoch=int(tools.current_security_epoch())
        binding=OperatorBinding(str(run.get('owner_id') or 'owner'),str(run.get('device_id') or ''),str(run.get('session_id') or ''),epoch,workflow_id=str(run['workflow_id']))
        plan={'steps':[{'kind':'workflow_uncertain_dispatch','run_id':run_id,'step_index':int(source['step_index']),'source_dispatch_id':source['dispatch_id'],'action_identity':source['action_identity']} ]}
        store.propose(txid,binding,goal='Reconcile uncertain workflow dispatch',action_plan=plan)
        tx=store.transaction(txid)
        if tx['state']=='proposed': store.transition(txid,'policy_check'); store.transition(txid,'permitted'); store.transition(txid,'executing')
        import hashlib
        action_id=f'{txid}:0'; store.start_action(txid,0,kind='workflow_uncertain_dispatch',parameter_hash=hashlib.sha256(source['action_identity'].encode()).hexdigest(),expected_postcondition='recover externally observed outcome before workflow continuation',target_identity=source['action_identity'])
        authority.ensure_recovery(txid,state='recovery_review_required',reason='workflow_dispatch_outcome_uncertain')
        lease=authority.acquire_lease(txid,'workflow-recovery-link')
        try:
            dispatch=authority.begin_dispatch(txid,action_id,operation_class='application_input',target=source['action_identity'],destination='',idempotency_key=source['dispatch_id'],worker_id='workflow-recovery-link',fencing_token=lease['fencing_token'])
            authority.mark_dispatched(dispatch['dispatch_id'],worker_id='workflow-recovery-link',fencing_token=lease['fencing_token'])
        finally: authority.release_lease(txid,'workflow-recovery-link',lease['fencing_token'])
        authority.set_state(txid,'recovery_review_required',reason='workflow_dispatch_outcome_uncertain',current_action_id=action_id,checkpoint={'workflow_id':run['workflow_id'],'run_id':run_id,'step_index':int(source['step_index']),'source_dispatch_id':source['dispatch_id']})
        self._update_run(run_id,recovery_transaction_id=txid,recovery_source_dispatch_id=source['dispatch_id'])
        self._emit('workflow.recovery_linked',run_id=run_id,workflow_id=run['workflow_id'],recovery_transaction_id=txid)
        return {'run_id':run_id,'recovery_transaction_id':txid,'recovery':authority.owner_view(txid)}

    def refresh_recovery(self,run_id,*,owner_id=None,device_id=None,session_id=None):
        run=self._run(run_id); self._assert_authority(run,owner_id=owner_id,device_id=device_id,session_id=session_id)
        txid=str(run.get('recovery_transaction_id') or '')
        if not txid: raise RuntimeError('workflow is not linked to W7 recovery')
        authority,_=self._recovery_authority(); view=authority.owner_view(txid); latest=authority.latest_verification(txid)
        state=str(view.get('recovery_state') or '')
        if latest and latest['result']=='verified_success':
            verification_id=str(latest['verification_id'])
            if str(run.get('recovery_consumed_verification_id') or '')!=verification_id:
                self.budgets.reconcile_uncertain_dispatch(run_id,run['recovery_source_dispatch_id'],resolution='verified_effect')
                completed=json.loads(run.get('completed_steps_json') or '[]'); step=int(run['current_step'])
                if not any(x.get('recovery_verification_id')==verification_id for x in completed):
                    completed.append({'step':step,'kind':'prompt','reply':'External effect verified through W7 recovery','recovered':True,'recovery_verification_id':verification_id})
                self._update_run(run_id,status='recovery_required',current_step=step+1,completed_steps_json=json.dumps(completed),recovery_consumed_verification_id=verification_id,error='W7 verified prior effect; owner may resume from next checkpoint',completed_at=None)
        elif latest and latest['result']=='verified_no_effect':
            decision=authority.retry_decision(txid,latest['action_id'])
            if decision.get('allowed'):
                self.budgets.reconcile_uncertain_dispatch(run_id,run['recovery_source_dispatch_id'],resolution='verified_no_effect')
                self._update_run(run_id,status='recovery_required',error='W7 verified no effect; owner may resume under retry policy',completed_at=None)
        elif state in {'abandoned_by_owner','cancelled'}:
            self._update_run(run_id,status='cancelled',error='workflow recovery terminated by governed W7 decision',completed_at=now())
            self.budgets.release(run_id,reason='W7 recovery terminated')
        return {'run_id':run_id,'status':self._run(run_id)['status'],'recovery':view}

    def resume_run(self,run_id,*,background=True,owner_id=None,device_id=None,session_id=None):
        run=self._run(run_id); self._assert_authority(run,owner_id=owner_id,device_id=device_id,session_id=session_id)
        if run['status'] not in {'recovery_required','interrupted'}: raise RuntimeError('workflow run is not waiting for recovery')
        wf=self.workflow(run['workflow_id'])
        if not wf['enabled'] or wf['paused']: raise RuntimeError('workflow must be enabled and unpaused before resuming')
        self.budgets.reacquire(run_id); self.budgets.check(run_id,next_step=int(run['current_step'])); self._update_run(run_id,status='queued',error=None,completed_at=None); self._emit('workflow.resumed',run_id=run_id,workflow_id=run['workflow_id'],checkpoint=int(run['current_step']))
        if background: self._workflow_pool.submit(self._continue_run,run_id)
        else: self._continue_run(run_id)
        return {'run_id':run_id,'resumed':True,'checkpoint':int(run['current_step'])}

    def _rollback(self,wf,completed,context,run,run_id):
        results=[]; by_pos={int(s['position']):s for s in wf['steps']}
        for item in reversed(completed):
            step=by_pos.get(int(item.get('step',-1)))
            if not step or not step.get('rollback_prompt') or not self.executor: continue
            try:
                self.budgets.check(run_id,next_step=int(item.get('step',0)),phase='rollback')
                with self.budgets.enter(run_id,int(item.get('step',0)),0,'rollback'): reply=self.executor.chat(self._render(str(step['rollback_prompt']),context),**self._authority_kwargs(run))
                results.append({'step':item.get('step'),'ok':True,'reply':reply})
            except Exception as exc: results.append({'step':item.get('step'),'ok':False,'error':type(exc).__name__})
        return results

    def _run(self,run_id):
        with self._con() as con: row=con.execute('SELECT * FROM workflow_runs WHERE id=?',(run_id,)).fetchone()
        if not row: raise KeyError('workflow run not found')
        return dict(row)
    def runs(self,workflow_id=None,limit=100):
        limit=max(1,min(int(limit),1000))
        with self._con() as con: rows=con.execute('SELECT * FROM workflow_runs WHERE workflow_id=? ORDER BY started_at DESC LIMIT ?',(workflow_id,limit)).fetchall() if workflow_id else con.execute('SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT ?',(limit,)).fetchall()
        out=[]
        for row in rows:
            item=dict(row); item.pop('session_id',None); item.pop('reauthenticated_at',None)
            try: item['budget']=self.budgets.status(item['id'])
            except KeyError: item['budget']=None
            out.append(item)
        return out
    def run_binding(self,run_id):
        """Read canonical workflow owner/device/session binding without exposing prompts or reauthentication data."""
        with self._con() as con:
            row=con.execute('SELECT owner_id,device_id,session_id FROM workflow_runs WHERE id=?',(str(run_id),)).fetchone()
        return dict(row) if row else None
    def budget_status(self,run_id): return self.budgets.status(run_id)
    def override_run_budget(self,run_id,updates,*,owner_id=None,device_id=None,session_id=None,reauthenticated_at=None):
        run=self._run(run_id); self._assert_authority(run,owner_id=owner_id,device_id=device_id,session_id=session_id)
        if reauthenticated_at is None or not (0 <= time.time()-float(reauthenticated_at) <= 300): raise PermissionError('recent owner reauthentication is required for workflow budget override')
        status=self.budgets.apply_owner_override(run_id,updates)
        if run['status']=='budget_exceeded': self._update_run(run_id,status='recovery_required',error='owner override applied; recovery review required',completed_at=None); self._emit('workflow.recovery_required',run_id=run_id,workflow_id=run['workflow_id'],reason='owner budget override applied')
        return status
    def _update_run(self,run_id,**fields):
        if not fields: return
        fields['updated_at']=now(); columns=','.join(f'{k}=?' for k in fields)
        unknown=set(fields)-self.RUN_UPDATE_FIELDS
        if unknown: raise ValueError(f'invalid workflow run fields: {sorted(unknown)}')
        with self._con() as con: con.execute(f'UPDATE workflow_runs SET {columns} WHERE id=?',[*fields.values(),run_id])
    def _emit(self,event,**payload):
        if self.events: self.events.emit(event,**payload)

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear(); self._thread=threading.Thread(target=self._loop,daemon=True,name='personal-ai-automation'); self._thread.start()
    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive(): self._thread.join(timeout=max(1.0,self.poll_seconds+.5))
        self._workflow_pool.shutdown(wait=False,cancel_futures=True); self._step_pool.shutdown(wait=False,cancel_futures=True)
    def _loop(self):
        while not self._stop.wait(self.poll_seconds):
            if self.executor:
                with self._con() as con: due=con.execute('SELECT * FROM automations WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at',(now(),)).fetchall()
                for row in due: self._run_one(row)
            self._run_due_workflows()
    def _run_due_workflows(self):
        with self._con() as con: rows=con.execute('SELECT * FROM workflows WHERE enabled=1 AND paused=0 AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at',(now(),)).fetchall()
        for row in rows:
            try: self.run_workflow(row['id'],trigger_payload={'type':'schedule'},background=True)
            except WorkflowBudgetError as exc: self._emit('workflow.skipped',workflow_id=row['id'],reason=exc.user_message)
            if row['interval_seconds']:
                nxt=datetime.fromtimestamp(now_ts()+int(row['interval_seconds']),timezone.utc).isoformat()
                with self._con() as con: con.execute('UPDATE workflows SET next_run_at=?,updated_at=? WHERE id=?',(nxt,now(),row['id']))
            else:
                with self._con() as con: con.execute('UPDATE workflows SET next_run_at=NULL,updated_at=? WHERE id=?',(now(),row['id']))
    def _run_one(self,row):
        result={'executed':False}
        try:
            condition=json.loads(row['condition_json'] or '{}'); context=self.context_provider() or {}
            if condition and not evaluate_condition(condition,context): result={'executed':False,'reason':'condition_false'}; self._emit('automation.skipped',automation_id=row['id'])
            else: result={'executed':True,'reply':self.executor.chat(row['prompt'])}; self._emit('automation.completed',automation_id=row['id'])
        except ConfirmationRequired as approval: result={'executed':False,'reason':'approval_required','approval_id':approval.approval_id}; self._emit('automation.approval_required',automation_id=row['id'],approval_id=approval.approval_id,tool=approval.tool_name)
        except Exception as exc: result={'executed':False,'error':sanitize_sensitive_text(str(exc))[:1000]}; self._emit('automation.failed',automation_id=row['id'],error=type(exc).__name__)
        finally:
            with self._con() as con:
                if row['interval_seconds']:
                    nxt=datetime.fromtimestamp(now_ts()+row['interval_seconds'],timezone.utc).isoformat(); con.execute('UPDATE automations SET last_run_at=?,next_run_at=?,last_result_json=? WHERE id=?',(now(),nxt,json.dumps(result),row['id']))
                else: con.execute('UPDATE automations SET last_run_at=?,enabled=0,last_result_json=? WHERE id=?',(now(),json.dumps(result),row['id']))
