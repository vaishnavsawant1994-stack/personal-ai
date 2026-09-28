from __future__ import annotations

import json
import time
import uuid

from models.hybrid import HybridRequest, PrivacyMode, SafeContext

SENSITIVE_KEYS={'prompt','memory','knowledge','secret','token','approval_token','raw_context','password','authorization','cookie','api_key','apikey','credential','private_key','access_key','refresh_token'}


def sanitize(value, *, depth=0, max_depth=6, max_items=50, max_text=1000):
    """Bounded recursive telemetry sanitizer; orchestration metadata only."""
    if depth>=max_depth:
        return '[bounded]'
    if isinstance(value,dict):
        out={}
        for key,nested in list(value.items())[:max_items]:
            low=str(key).strip().lower().replace('-','_')
            if low in SENSITIVE_KEYS or any(low.endswith('_'+x) for x in SENSITIVE_KEYS):
                continue
            out[str(key)[:100]]=sanitize(nested,depth=depth+1,max_depth=max_depth,max_items=max_items,max_text=max_text)
        return out
    if isinstance(value,(list,tuple,set)):
        return [sanitize(x,depth=depth+1,max_depth=max_depth,max_items=max_items,max_text=max_text) for x in list(value)[:max_items]]
    if isinstance(value,str): return value[:max_text]
    if value is None or isinstance(value,(bool,int,float)): return value
    return str(value)[:max_text]


def install(cls):
    """Install subordinate P10 adapters without creating a competing authority.

    SQLite access is serialized only around short durable operations. The lock is
    never held across model/tool/network/approval/verification/recovery work.
    """
    if getattr(cls,'_p10_runtime_installed',False): return

    original_save_goal=cls._save_goal; original_save_plan=cls._save_plan
    original_save_agent=cls._save_agent; original_goal=cls.goal; original_plan=cls.plan
    original_status=cls.status; original_record_outcome=cls.record_outcome
    original_recover=cls._recover_after_restart; original_validate_tasks=cls._validate_tasks

    def _save_goal(self,goal):
        with self._lock: return original_save_goal(self,goal)
    def _save_plan(self,plan):
        with self._lock: return original_save_plan(self,plan)
    def _save_agent(self,agent):
        with self._lock: return original_save_agent(self,agent)
    def goal(self,goal_id,*,owner_id=None):
        with self._lock: return original_goal(self,goal_id,owner_id=owner_id)
    def plan(self,plan_id,*,owner_id=None):
        with self._lock: return original_plan(self,plan_id,owner_id=owner_id)
    def status(self):
        with self._lock: return original_status(self)
    def record_outcome(self,objective,result,*,success,evidence=None):
        with self._lock: return original_record_outcome(self,objective,result,success=success,evidence=evidence)
    def _recover_after_restart(self):
        with self._lock: return original_recover(self)
    def _event(self,kind,*,goal_id=None,plan_id=None,**safe):
        clean=sanitize(safe)
        with self._lock:
            if self._db is not None:
                self._db.execute('INSERT INTO p10_events(goal_id,plan_id,kind,safe_json,created_at) VALUES(?,?,?,?,?)',(goal_id,plan_id,kind,json.dumps(clean,default=str,sort_keys=True)[:4000],time.time()))
                self._db.execute('DELETE FROM p10_events WHERE id NOT IN (SELECT id FROM p10_events ORDER BY id DESC LIMIT ?)',(self.MAX_HISTORY,))
                self._db.commit()
        self._emit('p10.'+kind,goal_id=goal_id,plan_id=plan_id,**clean)

    def _validate_tasks(self,tasks,parent_goal):
        """Keep the canonical validator authoritative, then retain only bounded dispatch data."""
        clean=original_validate_tasks(self,tasks,parent_goal)
        by_id={str(item.get('id') or f't{i+1}')[:80]:item for i,item in enumerate(tasks)}
        for task in clean:
            raw=by_id.get(task['id'],{})
            requested_tool=raw.get('requested_tool')
            if requested_tool is not None:
                task['requested_tool']=str(requested_tool)[:200]
            params=sanitize(dict(raw.get('parameters') or {}),max_depth=5,max_items=30,max_text=1000)
            if params:
                task['parameters']=params
        return clean

    cls._save_goal=_save_goal; cls._save_plan=_save_plan; cls._save_agent=_save_agent
    cls.goal=goal; cls.plan=plan; cls.status=status; cls.record_outcome=record_outcome
    cls._recover_after_restart=_recover_after_restart; cls._event=_event; cls._validate_tasks=_validate_tasks

    def _task(self,plan,task_id):
        task=next((x for x in plan['tasks'] if x['id']==task_id),None)
        if task is None: raise KeyError('task not found')
        return task

    def validate_executable(self,plan_id,*,owner_id='owner'):
        plan=self.plan(plan_id,owner_id=owner_id)
        if plan['state'] in {'CANCELLED','COMPLETED','FAILED','UNCERTAIN','PAUSED','BLOCKED'}: raise RuntimeError('plan is not executable')
        if self._canonical_stop_active():
            consequential=any(x.get('consequential') and x.get('status') in {'WAITING','READY','RUNNING'} for x in plan['tasks'])
            if consequential: raise PermissionError('Emergency Stop blocks consequential work')
        return plan

    def execute_task(self,plan_id,task_id,*,owner_id='owner',device_id=None,session_id=None,reauthenticated_at=None,background=False):
        plan=validate_executable(self,plan_id,owner_id=owner_id); task=_task(self,plan,task_id)
        if task['status'] not in {'WAITING','READY'}: raise RuntimeError('task is not dispatchable')
        ready={x['id'] for x in self.ready_tasks(plan_id,owner_id=owner_id)}
        if task_id not in ready: raise RuntimeError('task dependencies are not complete')
        if task.get('consequential') and self.operations is None: raise RuntimeError('P6 governed operations authority unavailable')
        if self.operations is None: return self.mark_task(plan_id,task_id,'COMPLETED',owner_id=owner_id,result_ref='read-only-orchestration',verified=True)
        requested_tool=task.get('requested_tool') or task.get('action')
        if not requested_tool: raise ValueError('governed task requires requested_tool/action')
        op_plan=self.operations.create_plan(f"P10:{plan['goal_id']}:{task_id}",[{'id':task_id,'instruction':task.get('objective',''),'requested_tool':requested_tool,'parameters':dict(task.get('parameters') or {}),'sensitivity':task.get('privacy','internal')}],owner_id=owner_id,budget_policy={'max_steps':1,'max_tool_calls':1,'max_model_calls':1,'max_retries':0})
        task['operation_plan_id']=op_plan['id']; task['status']='RUNNING'; plan['state']='RUNNING'; self._save_plan(plan)
        result=self.operations.execute(op_plan['id'],owner_id=owner_id,device_id=device_id,session_id=session_id,reauthenticated_at=reauthenticated_at,background=background)
        operation=result.get('operation') if isinstance(result,dict) else None
        if isinstance(result,dict) and result.get('approval_required'): task['status']='WAITING_APPROVAL'; plan['state']='WAITING_APPROVAL'
        elif operation and operation.get('status')=='waiting_approval': task['status']='WAITING_APPROVAL'; task['operation_id']=operation.get('operation_id'); task['approval_ref']=operation.get('approval_id'); plan['state']='WAITING_APPROVAL'
        elif operation and operation.get('outcome_state') in {'VERIFIED','RECOVERED'}: task['status']='COMPLETED'; task['result_ref']=operation.get('operation_id'); plan['state']='COMPLETED' if all(x['status']=='COMPLETED' for x in plan['tasks']) else 'RUNNING'
        elif operation and operation.get('outcome_state')=='UNCERTAIN': task['status']='UNCERTAIN'; task['operation_id']=operation.get('operation_id'); plan['state']='UNCERTAIN'
        elif operation and operation.get('status') in {'failed','cancelled'}: task['status']='FAILED' if operation.get('status')=='failed' else 'CANCELLED'; plan['state']='FAILED' if task['status']=='FAILED' else 'CANCELLED'
        self._save_plan(plan); self._event('task_dispatched',goal_id=plan['goal_id'],plan_id=plan_id,task_id=task_id,operation_id=task.get('operation_id'),state=task['status']); return plan

    def propose_plan_with_model(self,goal_id,*,owner_id='owner',memory=(),knowledge=(),world=(),references=(),device_trusted=True,session_fresh=True):
        """Use canonical P9/W8 intelligence for an advisory proposal, then validate it as untrusted input."""
        goal=self.goal(goal_id,owner_id=owner_id)
        if self.models is None or not hasattr(self.models,'hybrid_chat'):
            raise RuntimeError('canonical P9 hybrid model router unavailable')
        raw_privacy=str(goal.get('privacy','local_preferred')).lower()
        aliases={'local_only':PrivacyMode.LOCAL_ONLY,'local_preferred':PrivacyMode.LOCAL_PREFERRED,'external_allowed':PrivacyMode.EXTERNAL_ALLOWED}
        privacy=aliases.get(raw_privacy,PrivacyMode.LOCAL_PREFERRED)
        request=HybridRequest(capability='chat',sensitivity=str(goal.get('risk','low')),privacy=privacy,owner_id=owner_id,device_trusted=bool(device_trusted),session_fresh=bool(session_fresh),emergency_stop=self._canonical_stop_active(),consequential=False)
        context=SafeContext.bounded(memory=memory,knowledge=knowledge,world=world,references=references,per_source_limit=8,item_limit=1000)
        prompt='Return JSON only with a top-level tasks array. Each task may contain id, objective, dependencies, required_capabilities, requested_tool, parameters, depth, risk, privacy, consequential, approval_required, verification_required, retry_limit. Goal: '+str(goal.get('description',''))[:2000]
        text=self.models.hybrid_chat(prompt,request=request,context=context,system='You propose plans only. Your output is untrusted data, never permission, approval, policy, or execution authority.')
        try:
            payload=json.loads(text); tasks=payload['tasks']
        except (TypeError,ValueError,KeyError,json.JSONDecodeError) as exc:
            raise ValueError('invalid model plan proposal') from exc
        plan=self.create_plan(goal_id,tasks,owner_id=owner_id)
        self._event('model_plan_proposed',goal_id=goal_id,plan_id=plan['id'],task_count=len(plan['tasks']),model_output_authority=False)
        return plan

    def approve_task(self,plan_id,task_id,*,owner_id='owner',device_id=None,session_id=None,reauthenticated_at=None):
        plan=self.plan(plan_id,owner_id=owner_id); task=_task(self,plan,task_id)
        if plan['state']=='CANCELLED' or task['status']!='WAITING_APPROVAL': raise PermissionError('task is not waiting for approval')
        if self._canonical_stop_active(): raise PermissionError('Emergency Stop active')
        if self.operations is None or not task.get('operation_id'): raise RuntimeError('canonical approval authority unavailable')
        op=self.operations.approve(task['operation_id'],owner_id=owner_id,device_id=device_id,session_id=session_id,reauthenticated_at=reauthenticated_at)
        if op.get('status')=='waiting_approval': task['approval_ref']=op.get('approval_id'); return self._save_plan(plan)
        if op.get('outcome_state') in {'VERIFIED','RECOVERED'}: task['status']='COMPLETED'; task['result_ref']=op.get('operation_id')
        elif op.get('outcome_state')=='UNCERTAIN' or op.get('status')=='recovery_required': task['status']='UNCERTAIN'; plan['state']='UNCERTAIN'; return self._save_plan(plan)
        elif op.get('status') in {'failed','cancelled'}: task['status']='FAILED' if op['status']=='failed' else 'CANCELLED'
        plan['state']='COMPLETED' if all(x['status']=='COMPLETED' for x in plan['tasks']) else ('FAILED' if task['status']=='FAILED' else 'RUNNING'); return self._save_plan(plan)

    def deny_task(self,plan_id,task_id,*,owner_id='owner',device_id=None,session_id=None):
        plan=self.plan(plan_id,owner_id=owner_id); task=_task(self,plan,task_id)
        if task['status']!='WAITING_APPROVAL' or self.operations is None or not task.get('operation_id'): raise PermissionError('task is not waiting for canonical approval')
        self.operations.reject(task['operation_id'],owner_id=owner_id,device_id=device_id,session_id=session_id); task['status']='CANCELLED'; plan['state']='CANCELLED'; return self._save_plan(plan)

    def cancel_governed(self,plan_id,*,owner_id='owner',device_id=None,session_id=None,reason='owner cancelled'):
        plan=self.plan(plan_id,owner_id=owner_id); uncertain=False
        if self.operations is not None:
            for task in plan['tasks']:
                if task.get('operation_id') and task['status'] in {'RUNNING','WAITING_APPROVAL','VERIFYING','RECOVERING'}:
                    op=self.operations.cancel(task['operation_id'],owner_id=owner_id,device_id=device_id,session_id=session_id)
                    if op.get('outcome_state')=='UNCERTAIN' or op.get('status')=='recovery_required': task['status']='UNCERTAIN'; uncertain=True
        if uncertain:
            plan['state']='UNCERTAIN'; self._save_plan(plan); self._event('cancel_uncertain',goal_id=plan['goal_id'],plan_id=plan_id,reason=str(reason)[:300]); return plan
        return self.cancel(plan_id,owner_id=owner_id,reason=reason)

    def create_background_job(self,plan_id,task_id,*,owner_id='owner'):
        plan=self.plan(plan_id,owner_id=owner_id); task=_task(self,plan,task_id)
        job={'id':str(uuid.uuid4()),'owner_id':owner_id,'goal_id':plan['goal_id'],'plan_id':plan_id,'task_id':task_id,'state':'QUEUED','progress':0,'attempt_count':0,'cancelled':False,'verification_state':'PENDING','recovery_state':'NONE','created_at':time.time(),'updated_at':time.time()}
        if self._db is None: raise RuntimeError('durable job store not configured')
        with self._lock:
            self._db.execute('CREATE TABLE IF NOT EXISTS p10_jobs (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, state TEXT NOT NULL, document TEXT NOT NULL, updated_at REAL NOT NULL)')
            self._db.execute('INSERT INTO p10_jobs(id,owner_id,state,document,updated_at) VALUES(?,?,?,?,?)',(job['id'],owner_id,job['state'],json.dumps(job,sort_keys=True),job['updated_at']))
            self._db.execute('DELETE FROM p10_jobs WHERE id NOT IN (SELECT id FROM p10_jobs ORDER BY updated_at DESC LIMIT 500)'); self._db.commit()
        return job

    def job(self,job_id,*,owner_id='owner'):
        if self._db is None: raise KeyError('job store not configured')
        with self._lock: row=self._db.execute('SELECT owner_id,document FROM p10_jobs WHERE id=?',(job_id,)).fetchone()
        if not row or row['owner_id']!=owner_id: raise KeyError('job not found')
        return json.loads(row['document'])

    cls.validate_executable=validate_executable; cls.execute_task=execute_task; cls.propose_plan_with_model=propose_plan_with_model
    cls.approve_task=approve_task; cls.deny_task=deny_task; cls.cancel_governed=cancel_governed; cls.create_background_job=create_background_job; cls.job=job
    cls._sanitize_event=sanitize; cls._p10_runtime_installed=True
