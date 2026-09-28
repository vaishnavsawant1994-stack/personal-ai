from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import json
import threading
import time
from typing import Any

from desktop.application_context import ApplicationContextObserver
from desktop.controller import DesktopController
from desktop.observation_policy import ObservationSafetyError, bind_step_target, build_observation_record, canonical_digest, observation_context, verify_material_context
from desktop.operator_transactions import OperatorBinding, OperatorTransactionStore, new_transaction_id
from desktop.transactions import DesktopTransactionManager
from security.approvals import parameter_hash
from vision.screen_understanding import ScreenUnderstanding

ALLOWED_DESKTOP_ACTIONS = {'move', 'click', 'type_text', 'hotkey'}


@dataclass(frozen=True)
class ComputerPlanStep:
    kind: str
    params: dict[str, Any]
    reason: str = ''
    verify: str = ''
    expected_precondition: str = ''
    expected_postcondition: str = ''
    target: dict[str, Any] | None = None


class ComputerIntelligence:
    """Observe → bind → approve → re-observe → act → verify runtime."""

    def __init__(self, models, data_dir, *, second_brain=None, events=None, controller=None, emergency_stop=None, browser_session=None, application_observer=None):
        self.models=models; self.second_brain=second_brain; self.events=events; self.data_dir=Path(data_dir)
        self.screen=ScreenUnderstanding(models,data_dir); self.controller=controller or DesktopController(); self.transactions=DesktopTransactionManager(self.controller)
        self.operator_transactions=OperatorTransactionStore(self.data_dir/'operator-transactions.sqlite3'); self.emergency_stop=emergency_stop or (lambda:False)
        self.browser_session=browser_session; self.application_observer=application_observer or ApplicationContextObserver(); self._lock=threading.RLock()

    def _emit(self,name,**payload):
        if self.events:self.events.emit(name,**payload)

    def _browser_native_evidence(self):
        browser=self.browser_session
        if browser is None or getattr(browser,'context',None) is None or getattr(browser,'page',None) is None:return None
        try:return browser.capture_sanitized_screenshot()
        except Exception as exc:return {'available':False,'reason':f'browser_native_capture_failed:{type(exc).__name__}','bytes':b''}

    def _analyze_screen(self,question:str,*,monitor:int,**kwargs):
        try:return self.screen.analyze(question,monitor=monitor,**kwargs)
        except TypeError as exc:
            if 'unexpected keyword argument' not in str(exc):raise
            return self.screen.analyze(question,monitor=monitor)

    def observe(self,question: str='Describe the visible screen and the actionable UI elements relevant to the user.',monitor:int=1):
        self._emit('state',state='understanding')
        browser_source=self._browser_native_evidence()
        result=self._analyze_screen(question,monitor=monitor,redactions=None,sanitized_source=browser_source)
        self._emit('computer.observed',screenshot=result.get('screenshot_evidence_ref')); return result

    def _memory_context(self,goal:str):
        if not self.second_brain:return []
        try:return self.second_brain.context(goal,limit=5)
        except Exception:return []

    def plan(self,goal:str,*,observation:dict|None=None,max_steps:int=8):
        max_steps=max(1,min(int(max_steps),12)); observation=observation or self.observe(f'Describe the current UI and identify only elements relevant to this goal: {goal}'); memory=self._memory_context(goal)
        prompt=f'''Create a cautious desktop action plan for this goal:\n{goal}\n\nCURRENT SCREEN ANALYSIS:\n{observation.get('analysis', observation)}\n\nReturn JSON only with this shape:\n{{"summary":"...","steps":[{{"kind":"move|click|type_text|hotkey","params":{{}},"reason":"...","verify":"what should be visibly true after this action"}}]}}\nRules: at most {max_steps} steps; do not invent coordinates unless supported by screen evidence; do not submit purchases, send messages, delete data, change security settings, or type secrets unless the user's goal explicitly requires it. Prefer the smallest reversible sequence.'''
        data=self.models.json(
            prompt,
            system='You are Personal AI computer-control planner. Return bounded JSON only.',
            private_context=json.dumps(memory, default=str)[:5000],
        ); steps=[]
        for row in list(data.get('steps',[]))[:max_steps]:
            kind=str(row.get('kind','')).strip()
            if kind not in ALLOWED_DESKTOP_ACTIONS:raise ValueError(f'unsupported computer action: {kind}')
            params=dict(row.get('params') or {}); self._validate_params(kind,params); steps.append(ComputerPlanStep(kind=kind,params=params,reason=str(row.get('reason','')),verify=str(row.get('verify',''))))
        if not steps:raise ValueError('computer plan contained no executable steps')
        plan={'summary':str(data.get('summary','')),'steps':[step.__dict__ for step in steps]}; self._emit('computer.planned',goal=goal,step_count=len(steps)); return plan

    @staticmethod
    def _validate_params(kind:str,params:dict):
        if kind in {'move','click'}:
            if 'x' not in params or 'y' not in params:raise ValueError(f'{kind} requires x and y')
            for key in ('x','y'):
                value=int(params[key])
                if value < -10000 or value > 10000:raise ValueError(f'{key} is outside the allowed coordinate range')
                params[key]=value
        if kind=='type_text':
            text=str(params.get('text',''))
            if not text or len(text)>8000:raise ValueError('type_text requires 1-8000 characters')
            params['text']=text
        if kind=='hotkey':
            keys=list(params.get('keys') or [])
            if not 1<=len(keys)<=5 or any(len(str(key))>24 for key in keys):raise ValueError('hotkey requires 1-5 bounded key names')
            params['keys']=[str(key).lower() for key in keys]

    @staticmethod
    def _binding(context:dict)->OperatorBinding:
        required=('owner_id','device_id','session_id','security_epoch')
        if not isinstance(context,dict) or any(context.get(key) in (None,'') for key in required):raise PermissionError('trusted operator authority binding is required')
        return OperatorBinding(owner_id=str(context['owner_id']),device_id=str(context['device_id']),session_id=str(context['session_id']),security_epoch=int(context['security_epoch']),conversation_id=str(context.get('conversation_id') or ''),workflow_id=str(context.get('workflow_id') or ''))

    def _browser_snapshot(self):
        browser=self.browser_session
        if browser is None or getattr(browser,'context',None) is None or getattr(browser,'page',None) is None:return None
        try:return browser.observe()
        except Exception as exc:raise ObservationSafetyError('identity_unavailable',f'browser identity capture failed: {type(exc).__name__}') from exc

    def _capture_bound_observation(self,binding:OperatorBinding,txid:str,*,reason:str,question:str,monitor:int):
        app=self.application_observer.capture(); browser_snapshot=self._browser_snapshot(); browser_source=self._browser_native_evidence() if browser_snapshot is not None else None
        evidence_binding={'owner_id':binding.owner_id,'device_id':binding.device_id,'session_id':binding.session_id}
        result=self._analyze_screen(question,monitor=monitor,redactions=None,sanitized_source=browser_source,evidence_binding=evidence_binding,application_context=app)
        record=build_observation_record(binding=binding,transaction_id=txid,application=app,screen=result,browser=browser_snapshot,reason=reason,initiator='authenticated_transaction')
        self.operator_transactions.save_observation(record); return record,browser_snapshot,result

    def _bind_plan(self,plan:dict,*,observation:dict,browser_snapshot:dict|None,timeout_seconds:int):
        now=time.time(); steps=[]
        for raw in list(plan.get('steps') or []):
            row=deepcopy(raw); kind=str(row.get('kind') or ''); params=dict(row.get('params') or {})
            if kind not in ALLOWED_DESKTOP_ACTIONS:raise ValueError(f'unsupported computer action: {kind}')
            self._validate_params(kind,params); row['params']=params
            row['expected_precondition']=str(row.get('expected_precondition') or 'the bound application/window/target context is materially unchanged')[:1000]
            row['expected_postcondition']=str(row.get('expected_postcondition') or row.get('verify') or '')[:2000]; row['verify']=row['expected_postcondition']
            row['target']=bind_step_target(row,browser_snapshot=browser_snapshot,observation=observation,data_root=self.data_dir); steps.append(row)
        if not steps:raise ValueError('prepared operator plan is invalid')
        bound={'summary':str(plan.get('summary') or ''),'steps':steps,'observation_id':observation['observation_id'],'observation_digest':observation['observation_digest'],'expected_context':observation_context(observation),'plan_created_at':now,'plan_expires_at':min(float(observation['expires_at']),now+max(5,int(timeout_seconds)))}
        bound['canonical_plan_digest']=canonical_digest(bound); return bound

    def prepare_execution(self,parameters:dict)->dict:
        params=dict(parameters or {}); context=dict(params.get('_trusted_context') or {}); binding=self._binding(context); goal=str(params.get('goal') or '').strip()
        if not goal:raise ValueError('computer execution goal is required')
        max_steps=max(1,min(int(params.get('max_steps',8)),12)); monitor=int(params.get('monitor',1)); timeout_seconds=max(5,min(int(params.get('timeout_seconds',120)),600)); txid=str(params.get('_operator_transaction_id') or new_transaction_id())
        observation,browser_snapshot,screen_result=self._capture_bound_observation(binding,txid,reason='plan_creation',question=f'Describe the screen before preparing this goal: {goal}',monitor=monitor)
        raw_plan=params.get('_operator_plan')
        if not isinstance(raw_plan,dict):raw_plan=self.plan(goal,observation=screen_result,max_steps=max_steps)
        if len(list(raw_plan.get('steps') or []))>max_steps:raise ValueError('prepared operator plan is invalid')
        plan=self._bind_plan(raw_plan,observation=observation,browser_snapshot=browser_snapshot,timeout_seconds=timeout_seconds)
        record,created=self.operator_transactions.propose(txid,binding,goal=goal,action_plan=plan,deadline_at=min(time.time()+timeout_seconds,float(plan['plan_expires_at'])))
        if created:self.operator_transactions.transition(txid,'policy_check'); self.operator_transactions.transition(txid,'approval_required')
        elif record['state'] not in {'approval_required','permitted','completed'}:raise RuntimeError(f'operator transaction cannot be prepared from state {record["state"]}')
        params.update({'goal':goal,'max_steps':max_steps,'monitor':monitor,'timeout_seconds':timeout_seconds,'_trusted_context':context,'_operator_plan':plan,'_operator_transaction_id':txid,'_operator_observation_id':observation['observation_id'],'_operator_observation_digest':observation['observation_digest'],'_operator_plan_digest':plan['canonical_plan_digest']}); return params

    def reject_execution(self,parameters:dict):
        txid=str((parameters or {}).get('_operator_transaction_id') or '')
        if not txid:return False
        tx=self.operator_transactions.transaction(txid)
        if tx and tx['state']=='approval_required':self.operator_transactions.transition(txid,'cancelled',error_code='approval_rejected'); return True
        return False

    @staticmethod
    def _semantic_result(result:dict,expected:str):
        if not expected:return {'checked':False,'verified':True,'analysis':''}
        analysis=str(result.get('analysis') or ''); normalized=analysis.strip().upper(); return {'checked':True,'verified':normalized.startswith('VERIFIED') and not normalized.startswith('VERIFIED NOT'),'analysis':analysis}

    def _guard(self,txid:str,binding:OperatorBinding,cancel_event=None):
        tx=self.operator_transactions.assert_binding(txid,binding)
        if self.emergency_stop():
            if tx['state'] not in {'completed','failed','cancelled','recovery_review_required'}:self.operator_transactions.transition(txid,'cancelled',error_code='emergency_stop')
            raise PermissionError('owner emergency stop is active')
        if cancel_event is not None and cancel_event.is_set():self.operator_transactions.request_cancel(txid)
        tx=self.operator_transactions.transaction(txid)
        if tx and tx['cancel_requested']:
            if tx['state'] not in {'completed','failed','cancelled','recovery_review_required'}:self.operator_transactions.transition(txid,'cancelled',error_code='cancelled')
            raise RuntimeError('computer execution cancelled by user')
        if tx and tx.get('deadline_at') is not None and time.time()>=float(tx['deadline_at']):
            if tx['state'] not in {'completed','failed','cancelled','recovery_review_required'}:self.operator_transactions.transition(txid,'failed',error_code='observation_expired')
            raise ObservationSafetyError('observation_expired','computer execution deadline exceeded')
        return tx

    def _validate_prepared_binding(self,params:dict,tx:dict,plan:dict):
        digest=canonical_digest({k:v for k,v in plan.items() if k!='canonical_plan_digest'})
        if digest!=plan.get('canonical_plan_digest') or digest!=params.get('_operator_plan_digest'):raise PermissionError('approved operator plan digest mismatch')
        if tx.get('plan')!=plan:raise PermissionError('approved operator plan no longer matches the durable transaction')
        obs=self.operator_transactions.observation(str(params.get('_operator_observation_id') or ''))
        if not obs or obs.get('observation_digest')!=params.get('_operator_observation_digest') or obs.get('observation_digest')!=plan.get('observation_digest'):raise PermissionError('approved operator observation digest mismatch')
        if time.time()>=float(plan.get('plan_expires_at') or 0):raise ObservationSafetyError('observation_expired','approved operator plan expired')
        return obs

    def execute_prepared(self,parameters:dict,*,cancel_event=None):
        params=dict(parameters or {})
        if not params.get('_personal_ai_prepared'):raise PermissionError('computer execution requires a Personal AI prepared and approved plan')
        context=dict(params.get('_trusted_context') or {}); binding=self._binding(context); txid=str(params.get('_operator_transaction_id') or ''); plan=params.get('_operator_plan')
        if not txid or not isinstance(plan,dict):raise PermissionError('computer execution is missing its approved operator transaction')
        goal=str(params.get('goal') or ''); monitor=int(params.get('monitor',1))
        with self._lock:
            tx=self.operator_transactions.assert_binding(txid,binding)
            if tx['state']=='completed':return {'ok':True,'verified':True,'transaction_id':txid,'deduplicated':True,'state':'completed'}
            expected_observation=self._validate_prepared_binding(params,tx,plan)
            if tx['state']=='approval_required':self.operator_transactions.transition(txid,'permitted')
            self.operator_transactions.assert_dispatchable(txid,binding); self._guard(txid,binding,cancel_event); self.operator_transactions.transition(txid,'executing')
            physical_tx=self.transactions.begin(); evidence=[]; uncertain=False; self._emit('state',state='acting'); self._emit('computer.execution.started',transaction_id=txid,goal=goal,step_count=len(plan.get('steps',[])))
            try:
                for index,row in enumerate(list(plan.get('steps') or []),start=1):
                    self._guard(txid,binding,cancel_event); step=ComputerPlanStep(**row); self._validate_params(step.kind,step.params)
                    before_obs,before_browser,_=self._capture_bound_observation(binding,txid,reason='pre_dispatch_revalidation',question=f'Revalidate the current screen before step {index}; do not act.',monitor=monitor)
                    verify_material_context(expected=expected_observation,current=before_obs,target_binding=step.target or {},current_browser=before_browser,data_root=self.data_dir); self._guard(txid,binding,cancel_event)
                    action,created=self.operator_transactions.start_action(txid,index,kind=step.kind,parameter_hash=parameter_hash(step.params),expected_postcondition=step.expected_postcondition or step.verify,before_observation_id=before_obs['observation_id'],target_identity=str((step.target or {}).get('target_id') or ''),plan_digest=plan['canonical_plan_digest'],observation_digest=before_obs['observation_digest'])
                    if not created:
                        if action.get('state')=='verified':evidence.append({'step':index,'kind':step.kind,'deduplicated':True,'verified':True}); expected_observation=self.operator_transactions.observation(action.get('after_observation_id')); continue
                        raise RuntimeError('operator action requires recovery review before redispatch')
                    try:
                        self._guard(txid,binding,cancel_event); result=self.transactions.execute(physical_tx,step.kind,**step.params)
                    except Exception as exc:
                        uncertain=True; self.operator_transactions.transition(txid,'recovery_review_required',error_code=type(exc).__name__,recovery_reason='desktop_dispatch_outcome_uncertain')
                        try:self.transactions.rollback(physical_tx)
                        except Exception:pass
                        raise
                    if not result.get('verified'):
                        uncertain=True; self.operator_transactions.finish_action(action['action_id'],verified=False,evidence={'action_verified':False},error_code='verification_failed'); self.operator_transactions.transition(txid,'recovery_review_required',error_code='verification_failed',recovery_reason='desktop_action_change_unverified'); self.transactions.rollback(physical_tx); raise ObservationSafetyError('verification_failed',f'computer action did not produce a verifiable change: step {index}')
                    question=(f'Verify this UI postcondition: {step.expected_postcondition or step.verify}. Start the answer with VERIFIED or NOT_VERIFIED, then one short reason.' if (step.expected_postcondition or step.verify) else 'Describe the visible state after the action.')
                    after_obs,_,after_result=self._capture_bound_observation(binding,txid,reason='post_dispatch_verification',question=question,monitor=monitor); semantic=self._semantic_result(after_result,step.expected_postcondition or step.verify)
                    if semantic['checked'] and not semantic['verified']:
                        uncertain=True; self.operator_transactions.finish_action(action['action_id'],verified=False,evidence={'action_verified':True,'semantic_checked':True,'before_observation_id':before_obs['observation_id'],'after_observation_id':after_obs['observation_id']},error_code='verification_failed',after_observation_id=after_obs['observation_id']); self.operator_transactions.transition(txid,'recovery_review_required',error_code='verification_failed',recovery_reason='semantic_postcondition_failed'); self.transactions.rollback(physical_tx); raise ObservationSafetyError('verification_failed',f'computer postcondition failed at step {index}')
                    safe_evidence={'action_verified':True,'semantic_checked':bool(semantic['checked']),'semantic_verified':bool(semantic['verified']),'before_observation_id':before_obs['observation_id'],'before_evidence_ref':before_obs['screenshot_evidence_ref'],'before_sha256':before_obs['screen_fingerprint'],'after_observation_id':after_obs['observation_id'],'after_evidence_ref':after_obs['screenshot_evidence_ref'],'after_sha256':after_obs['screen_fingerprint']}
                    self.operator_transactions.finish_action(action['action_id'],verified=True,evidence=safe_evidence,after_observation_id=after_obs['observation_id']); evidence.append({'step':index,'kind':step.kind,**safe_evidence}); expected_observation=after_obs; self._emit('computer.step.verified',transaction_id=txid,step=index,kind=step.kind)
                self.operator_transactions.transition(txid,'verifying'); self._guard(txid,binding,cancel_event); committed=self.transactions.commit(physical_tx); self.operator_transactions.transition(txid,'completed')
                output={'ok':True,'verified':True,'goal':goal,'transaction_id':txid,'plan_digest':plan['canonical_plan_digest'],'evidence':evidence,'final_observation':expected_observation,**committed}; self._emit('computer.execution.completed',transaction_id=txid,goal=goal); return output
            except Exception as exc:
                current=self.operator_transactions.transaction(txid)
                if current and current['state'] in {'executing','verifying'}:
                    code=getattr(exc,'code',type(exc).__name__); target='recovery_review_required' if uncertain else 'failed'; self.operator_transactions.transition(txid,target,error_code=str(code)[:120],recovery_reason='execution_outcome_uncertain' if uncertain else '')
                    try:self.transactions.rollback(physical_tx)
                    except Exception:pass
                self._emit('computer.execution.failed',transaction_id=txid,goal=goal,error_type=type(exc).__name__); raise

    def execute(self,goal:str,*,plan:dict|None=None,max_steps:int=8,monitor:int=1,cancel_event=None):
        """Legacy isolated direct entry. Exposed tools use execute_prepared."""
        with self._lock:
            if cancel_event is not None and cancel_event.is_set():raise RuntimeError('computer execution cancelled before start')
            initial=self.observe(f'Describe the screen before executing this goal: {goal}',monitor=monitor); plan=plan or self.plan(goal,observation=initial,max_steps=max_steps); steps=[ComputerPlanStep(**row) for row in list(plan.get('steps',[]))[:max_steps]]; tx=self.transactions.begin(); evidence=[]
            try:
                for index,step in enumerate(steps):
                    if cancel_event is not None and cancel_event.is_set():raise RuntimeError('computer execution cancelled by user')
                    self._validate_params(step.kind,step.params); result=self.transactions.execute(tx,step.kind,**step.params)
                    if not result.get('verified'):raise RuntimeError(f'computer action did not produce a verifiable change: step {index+1}')
                    semantic_result=self.observe(f'Verify this UI postcondition: {step.verify}. Start the answer with VERIFIED or NOT_VERIFIED.',monitor=monitor); semantic=self._semantic_result(semantic_result,step.verify)
                    if semantic['checked'] and not semantic['verified']:raise RuntimeError(f'computer postcondition failed at step {index+1}')
                    evidence.append({'step':index+1,'kind':step.kind,'action_verified':True,'semantic_verify':semantic})
                final=self.observe(f'Describe the completed state for this goal: {goal}',monitor=monitor); committed=self.transactions.commit(tx); return {'ok':True,'verified':True,'goal':goal,'transaction_id':tx.id,'plan':plan,'evidence':evidence,'final':final,**committed}
            except Exception:
                self.transactions.rollback(tx); raise
