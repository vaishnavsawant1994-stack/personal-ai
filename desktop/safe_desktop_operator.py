from __future__ import annotations

from dataclasses import dataclass,field
import hashlib,json,time,uuid
from pathlib import Path
from typing import Any,Callable

from desktop.application_context import ApplicationContextObserver
from desktop.file_operator import SafeFileAdapter
from desktop.input_clipboard import UnsupportedClipboardAdapter,validate_hotkey
from desktop.operator_transactions import OperatorBinding,OperatorTransactionStore
from desktop.platform_adapter import DesktopPlatformAdapter,default_desktop_adapter
from security.policy_gateway import DecisionKind,PolicyGateway,PolicyOperation
from security.policy_targets import TargetValidationError,canonical_path,classify_clipboard


def digest(value:Any)->str:return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

@dataclass(frozen=True)
class DesktopAction:
    kind:str;transaction_id:str;sequence:int=0;executable:str='';args:list[str]=field(default_factory=list);window_id:str='';target_id:str='';x:int|None=None;y:int|None=None;width:int|None=None;height:int|None=None;text:str='';option:str='';keys:tuple[str,...]=();amount:int=0;path:str='';destination:str='';roots:list[str]=field(default_factory=list);trash_root:str='';claimed_mime:str='';data_classification:str='public';parameters:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class DesktopResult:
    status:str;reason_code:str;transaction_id:str;rollback:str='manual_recovery_only';before_observation_id:str='';after_observation_id:str='';result:dict[str,Any]=field(default_factory=dict)

class SafeDesktopOperator:
    FILE_KINDS={'file_metadata','read_file','create_file','copy','move','rename','mkdir','trash','permanent_delete','checksum','list_dir'}
    INPUT_KINDS={'click','type','select','hotkey','scroll'}
    WINDOW_KINDS={'focus','minimize','maximize','restore','move_resize','close_window'}
    READ_ONLY={'file_metadata','read_file','list_dir','checksum','read_ui','clipboard_read'}
    REVERSIBILITY={'create_file':'reversible','copy':'reversible','move':'reversible','rename':'reversible','mkdir':'reversible','trash':'compensating_action_available','permanent_delete':'irreversible'}

    def __init__(self,policy:PolicyGateway,transactions:OperatorTransactionStore,binding:OperatorBinding,*,desktop:DesktopPlatformAdapter|None=None,files:SafeFileAdapter|None=None,clipboard=None,context:ApplicationContextObserver|None=None,emergency_stop:Callable[[],bool]|None=None,visual_verifier:Callable[[DesktopAction],bool]|None=None):
        self.policy=policy;self.transactions=transactions;self.binding=binding;self.desktop=desktop or default_desktop_adapter();self.files=files or SafeFileAdapter();self.clipboard=clipboard or UnsupportedClipboardAdapter();self.context=context or ApplicationContextObserver();self.emergency_stop=emergency_stop or (lambda:False);self.visual_verifier=visual_verifier or (lambda action:False)

    def execute(self,a:DesktopAction,*,approved=False,reauthenticated=False)->DesktopResult:
        try:self._validate(a);tx=self._ensure_tx(a)
        except Exception as exc:return self._result(a,'blocked_by_policy',self._reason(exc))
        if tx.get('state')=='recovery_review_required':return self._result(a,'recovery_review_required','recovery_review_required')
        if tx.get('cancel_requested'):return self._cancel(a,'cancelled')
        if self.emergency_stop():return self._cancel(a,'emergency_stop_active')
        try:before=self._capture(a,'policy_evaluation');ops=self._policy_operations(a,before)
        except Exception as exc:return self._result(a,'blocked_by_policy',self._reason(exc))
        decisions=[]
        for op in ops:
            decision=self.policy.evaluate(op,approved=approved,reauthenticated=reauthenticated);decisions.append((op,decision))
            outcome=self._decision_outcome(a,before,decision)
            if outcome:return outcome
        if a.kind=='close_window' and a.parameters.get('unsaved_work') and not approved:
            self._approval_state(a.transaction_id);return self._result(a,'approval_required','approval_required',before=before)
        try:
            self._permit_state(a.transaction_id);fresh=self._capture(a,'pre_dispatch');self._assert_fresh(before,fresh,a)
            if self.emergency_stop():return self._deny(a,fresh,'emergency_stop_active')
            self.transactions.assert_dispatchable(a.transaction_id,self.binding)
            fresh_ops=self._policy_operations(a,fresh);second_decisions=[]
            # Evaluate the complete policy set before consuming any permit. Permit consumption increments
            # policy use counters, so interleaving evaluate/consume would falsely look like a policy change.
            for (old_op,old_decision),rebound in zip(decisions,fresh_ops):
                expected_clip=''
                if old_op.target_type=='clipboard' and old_op.parameters.get('clipboard_content') is not None:
                    expected_clip=classify_clipboard(old_op.parameters['clipboard_content'],max_bytes=int(old_op.target_identity.get('max_bytes') or 64*1024))['sha256']
                second=self.policy.evaluate(rebound,approved=approved,reauthenticated=reauthenticated,expected_policy_digest=old_decision.policy_digest,expected_clipboard_digest=expected_clip)
                if second.decision is not DecisionKind.ALLOW:return self._deny(a,fresh,second.reason_code)
                second_decisions.append((rebound,second))
            permits=[self.policy.issue_temporary_permit(op,decision,ttl_seconds=90) for op,decision in second_decisions]
            for permit,(op,decision) in zip(permits,second_decisions):
                if not self.policy.consume_temporary_permit(permit['permit_id'],op,decision):return self._deny(a,fresh,'policy_changed')
            target=self._target_identity(a);self.transactions.transition(a.transaction_id,'executing')
            row,created=self.transactions.start_action(a.transaction_id,a.sequence,kind=a.kind,parameter_hash=digest(self._safe_params(a)),expected_postcondition='verified W7.5 postcondition or recovery review',before_observation_id=fresh['observation_id'],target_identity=target,plan_digest=digest({'kind':a.kind,'target':target}),observation_digest=fresh['observation_digest'])
            if not created:self._recovery(a.transaction_id,'duplicate_dispatch_uncertain');return self._result(a,'recovery_review_required','recovery_review_required',before=fresh)
            try:raw=self._dispatch(a)
            except Exception as exc:
                self._release_input()
                if self._consequential(a):
                    for permit in permits:self.policy.mark_unknown_outcome(permit['permit_id'],'desktop_dispatch_exception')
                    self._recovery(a.transaction_id,'desktop_dispatch_exception');return self._result(a,'recovery_review_required','recovery_review_required',before=fresh)
                code=self._reason(exc);self.transactions.finish_action(row['action_id'],verified=False,error_code=code);self.transactions.transition(a.transaction_id,'failed',error_code=code);return self._result(a,'verification_failed',code,before=fresh)
            self.transactions.transition(a.transaction_id,'verifying');after=self._capture(a,'postcondition_verification');ok,reason=self._verify(a,fresh,after,raw)
            self.transactions.finish_action(row['action_id'],verified=ok,evidence=self._safe_evidence(raw),error_code='' if ok else reason,after_observation_id=after['observation_id'])
            if not ok:
                if self._consequential(a):self._recovery(a.transaction_id,reason);return self._result(a,'recovery_review_required','recovery_review_required',before=fresh,after=after)
                self.transactions.transition(a.transaction_id,'failed',error_code=reason);return self._result(a,'verification_failed','verification_failed',before=fresh,after=after)
            self.transactions.transition(a.transaction_id,'completed')
            return self._result(a,'verified','allow',before=fresh,after=after,result=self._caller_result(a,raw),rollback=self.REVERSIBILITY.get(a.kind,'manual_recovery_only'))
        except Exception as exc:self._release_input();return self._deny(a,before,self._reason(exc))

    def _decision_outcome(self,a,before,decision):
        if decision.decision is DecisionKind.REAUTHENTICATION_REQUIRED:self._approval_state(a.transaction_id);return self._result(a,'reauthentication_required',decision.reason_code,before=before)
        if decision.decision is DecisionKind.APPROVAL_REQUIRED:self._approval_state(a.transaction_id);return self._result(a,'approval_required',decision.reason_code,before=before)
        if decision.decision is DecisionKind.RECOVERY_REVIEW_REQUIRED:return self._result(a,'recovery_review_required',decision.reason_code,before=before)
        if decision.decision is not DecisionKind.ALLOW:return self._deny(a,before,decision.reason_code)
        return None

    def _path_state(self,path,roots):
        if not path:return {}
        try:return self.files.metadata(path,roots)
        except FileNotFoundError:return {'exists':False}
        except TargetValidationError:raise
        except Exception:return {'exists':False}

    def _capture(self,a,reason):
        now=time.time();app=self.context.capture();clip_sha='';clip_seq=None;clip_content=''
        if a.kind.startswith('clipboard_'):
            clip_content,seq=self.clipboard.read_text();meta=classify_clipboard(clip_content,max_bytes=int(a.parameters.get('max_bytes') or 64*1024));clip_sha=meta['sha256'];clip_seq=int(seq)
        source=self._path_state(a.path,a.roots) if a.path and a.roots else {};dest=self._path_state(a.destination,a.roots) if a.destination and a.roots else {}
        obs={'application':app,'source_state':source,'destination_state':dest,'clipboard_sha256':clip_sha,'clipboard_sequence':clip_seq,'captured_at':now}
        if a.kind.startswith('clipboard_'):obs['_clipboard_content']=clip_content
        od=digest({k:v for k,v in obs.items() if k!='_clipboard_content'});oid=f'w75-{uuid.uuid4().hex}';appid=str(app.get('identity_digest') or ('filesystem' if a.kind in self.FILE_KINDS else 'clipboard' if a.kind.startswith('clipboard_') else 'desktop'));process=str(app.get('process_start_token') or app.get('process_id') or appid);window=str(app.get('window_id') or f'{appid}:bounded')
        self.transactions.save_observation({'observation_id':oid,'transaction_id':a.transaction_id,'owner_id':self.binding.owner_id,'device_id':self.binding.device_id,'session_id':self.binding.session_id,'security_epoch':self.binding.security_epoch,'application_identity':appid,'application_name':app.get('application',''),'process_identity':process,'window_identity':window,'captured_at':now,'expires_at':now+90,'screenshot_evidence_ref':'not_captured_w75_metadata_only','screen_fingerprint':digest({'app':appid,'window':window,'source':source.get('sha256',''),'destination':dest.get('sha256',''),'clipboard':clip_sha}),'sanitized_dom_digest':'','accessibility_tree_digest':'','actionable_element_digest':'','frame_origins_digest':'','active_target_id':a.target_id,'sensitivity':{'clipboard_present':bool(clip_sha)},'capture_reason':reason,'capture_initiator':'w7.5_safe_desktop_operator','observation_digest':od})
        obs.update({'observation_id':oid,'observation_digest':od});return obs

    def _path_op(self,operation,path,a,obs):return PolicyOperation(operation,self.binding.owner_id,self.binding.device_id,self.binding.session_id,self.binding.security_epoch,'path',{'path':path,'approved_roots':list(a.roots)},None,path,self._safe_params(a),a.data_classification,obs.get('observation_id',''),obs.get('observation_digest',''))
    def _policy_operations(self,a,obs):
        if a.kind in self.FILE_KINDS:
            if a.kind in {'file_metadata','read_file','list_dir','checksum'}:return [self._path_op('read',a.path,a,obs)]
            if a.kind in {'create_file','mkdir'}:return [self._path_op('local_file_write',a.path,a,obs)]
            if a.kind=='copy':return [self._path_op('read',a.path,a,obs),self._path_op('local_file_write',a.destination,a,obs)]
            if a.kind in {'move','rename'}:return [self._path_op('delete',a.path,a,obs),self._path_op('local_file_write',a.destination,a,obs)]
            if a.kind=='trash':return [self._path_op('delete',a.path,a,obs),self._path_op('local_file_write',a.trash_root,a,obs)]
            return [self._path_op('destructive_delete',a.path,a,obs)]
        if a.kind.startswith('clipboard_'):
            destination=str(a.parameters.get('destination') or 'clipboard');target={'destination':destination,'max_bytes':int(a.parameters.get('max_bytes') or 64*1024)};params=self._safe_params(a);content=a.text if a.kind=='clipboard_write' else str(obs.get('_clipboard_content') or '')
            if a.kind!='clipboard_clear':params['clipboard_content']=content
            operation={'clipboard_read':'clipboard_read','clipboard_clear':'clipboard_write'}.get(a.kind,'clipboard_write' if destination=='clipboard' else 'clipboard_transfer')
            return [PolicyOperation(operation,self.binding.owner_id,self.binding.device_id,self.binding.session_id,self.binding.security_epoch,'clipboard',target,None,destination,params,a.data_classification,obs.get('observation_id',''),obs.get('observation_digest',''))]
        executable=a.executable if a.kind=='launch' else str(a.parameters.get('executable') or '')
        if not executable:raise PermissionError('application_not_allowed')
        app=self.desktop.application_identity(executable);operation={'launch':'launch','focus':'control','minimize':'control','maximize':'control','restore':'control','move_resize':'control','close_window':'control','click':'application_input','type':'application_input','select':'application_input','hotkey':'application_input','scroll':'application_input','read_ui':'read'}[a.kind]
        return [PolicyOperation(operation,self.binding.owner_id,self.binding.device_id,self.binding.session_id,self.binding.security_epoch,'application',app,app,a.window_id or a.executable,self._safe_params(a),a.data_classification,obs.get('observation_id',''),obs.get('observation_digest',''))]

    def _verified_control(self,a):
        try:state=self.desktop.control_state(a.target_id) if a.target_id else None
        except Exception:state=None
        if state:
            if state.get('window_id')!=a.window_id or not state.get('visible',False) or not state.get('enabled',False):raise PermissionError('target_changed')
            return state
        if a.kind=='click' and a.parameters.get('verified_visual_target_id')==a.target_id and a.parameters.get('visual_target_digest') and a.parameters.get('visual_observation_digest') and self.visual_verifier(a):return {'visual_fallback':True}
        raise PermissionError('target_changed')

    def _dispatch(self,a):
        if a.kind=='launch':return self.desktop.launch(a.executable,list(a.args))
        if a.kind=='focus':return {'focused':self.desktop.focus_window(a.window_id)}
        if a.kind in {'minimize','maximize','restore','close_window'}:return {'window_action':self.desktop.window_action(a.window_id,a.kind.replace('_window',''))}
        if a.kind=='move_resize':return {'window_action':self.desktop.window_action(a.window_id,'move_resize',x=a.x,y=a.y,width=a.width,height=a.height)}
        if a.kind in self.INPUT_KINDS:
            fg=self.desktop.foreground_window()
            if not fg or not fg.foreground or fg.window_id!=a.window_id:raise PermissionError('window_changed')
            if not fg.visible or not fg.enabled:raise PermissionError('target_changed')
            if self.emergency_stop():raise PermissionError('emergency_stop_active')
            control=self._verified_control(a) if a.kind in {'click','type','select'} else None
            if a.kind=='click':self.desktop.input_click(int(a.x),int(a.y));return {'input':'click','target_id':a.target_id,'visual_fallback':bool(control.get('visual_fallback'))}
            if a.kind=='type':self.desktop.input_type(a.text);return {'input':'type','target_id':a.target_id,'value_digest':digest(a.text)}
            if a.kind=='select':self.desktop.input_select(a.target_id,a.option);return {'input':'select','target_id':a.target_id,'option_digest':digest(a.option)}
            if a.kind=='hotkey':keys=validate_hotkey(a.keys);self.desktop.input_hotkey(keys);return {'input':'hotkey','keys':list(keys)}
            amount=max(-1200,min(1200,int(a.amount)));self.desktop.input_scroll(amount);return {'input':'scroll','amount':amount}
        if a.kind=='read_ui':return {'visible_text':self.desktop.read_visible_text(a.window_id,max_chars=min(int(a.parameters.get('max_chars') or 12000),12000))}
        if a.kind=='file_metadata':return self.files.metadata(a.path,a.roots)
        if a.kind=='list_dir':return {'entries':self.files.list_dir(a.path,a.roots,limit=int(a.parameters.get('limit') or 500))}
        if a.kind=='checksum':return {'sha256':self.files.checksum(self.files._safe(a.path,a.roots,must_exist=True))}
        if a.kind=='read_file':return {'text':self.files.read_text(a.path,a.roots,max_bytes=int(a.parameters.get('max_bytes') or 1024*1024))}
        if a.kind=='create_file':return self.files.create_file(a.path,a.roots,a.text,claimed_mime=a.claimed_mime).__dict__
        if a.kind=='mkdir':return self.files.create_dir(a.path,a.roots).__dict__
        if a.kind=='copy':return self.files.copy(a.path,a.destination,a.roots,claimed_mime=a.claimed_mime).__dict__
        if a.kind=='move':return self.files.move(a.path,a.destination,a.roots).__dict__
        if a.kind=='rename':return self.files.rename(a.path,a.destination,a.roots).__dict__
        if a.kind=='trash':return self.files.trash(a.path,a.roots,a.trash_root).__dict__
        if a.kind=='permanent_delete':return self.files.permanent_delete(a.path,a.roots).__dict__
        if a.kind=='clipboard_read':
            text,seq=self.clipboard.read_text();meta=classify_clipboard(text,max_bytes=int(a.parameters.get('max_bytes') or 64*1024));return {'sequence':seq,'sha256':meta['sha256'],'classification':meta['classification'],'size':meta['size']}
        if a.kind=='clipboard_write':
            meta=classify_clipboard(a.text,max_bytes=int(a.parameters.get('max_bytes') or 64*1024));return {'sequence':self.clipboard.write_text(a.text),'sha256':meta['sha256'],'classification':meta['classification'],'size':meta['size']}
        if a.kind=='clipboard_clear':return {'sequence':self.clipboard.clear(),'cleared':True}
        raise ValueError('unsupported_action')

    def _verify(self,a,before,after,raw):
        if a.kind=='launch':return bool(raw.get('process_id') and raw.get('application',{}).get('sha256') and raw.get('window')),'launch_verified'
        if a.kind=='focus':return bool(raw.get('focused') and (after.get('application') or {}).get('window_id')==a.window_id),'focus_verified'
        if a.kind in self.WINDOW_KINDS:return bool(raw.get('window_action')),'window_verified'
        if a.kind in self.INPUT_KINDS:return True,'foreground_target_input_verified'
        if a.kind in self.FILE_KINDS:return bool(raw.get('verified',True)),'file_postcondition_verified'
        if a.kind=='clipboard_write':return after.get('clipboard_sha256')==raw.get('sha256'),'clipboard_verified'
        if a.kind=='clipboard_clear':return after.get('clipboard_sha256')==hashlib.sha256(b'').hexdigest(),'clipboard_verified'
        return True,'clipboard_read_verified' if a.kind=='clipboard_read' else 'verified'

    def _assert_fresh(self,before,after,a):
        if time.time()-float(before.get('captured_at') or 0)>90:raise PermissionError('observation_expired')
        if a.kind in self.INPUT_KINDS|self.WINDOW_KINDS:
            b=before.get('application') or {};c=after.get('application') or {}
            if b.get('window_id') and c.get('window_id') and b.get('window_id')!=c.get('window_id'):raise PermissionError('window_changed')
        for key in ('source_state','destination_state'):
            b=before.get(key) or {};c=after.get(key) or {}
            if bool(b.get('exists'))!=bool(c.get('exists')) or (b.get('sha256') and c.get('sha256') and b.get('sha256')!=c.get('sha256')):raise PermissionError('path_changed')
        if a.kind.startswith('clipboard_') and before.get('clipboard_sequence')!=after.get('clipboard_sequence'):raise PermissionError('clipboard_changed')

    def _validate(self,a):
        allowed={'launch','focus','minimize','maximize','restore','move_resize','close_window','click','type','select','hotkey','scroll','read_ui',*self.FILE_KINDS,'clipboard_read','clipboard_write','clipboard_clear'}
        if a.kind not in allowed or not a.transaction_id:raise ValueError('invalid_action')
        if a.kind=='launch' and (not a.executable or not Path(a.executable).is_absolute()):raise PermissionError('application_not_allowed')
        if a.kind in self.FILE_KINDS:
            if not a.path or not a.roots:raise PermissionError('path_not_allowed')
            canonical_path(a.path,a.roots)
            if a.destination:canonical_path(a.destination,a.roots)
            if a.kind=='trash':canonical_path(a.trash_root,a.roots)
        if a.kind in self.INPUT_KINDS:
            if not a.window_id:raise PermissionError('window_changed')
            if a.kind in {'click','type','select'} and not a.target_id:raise PermissionError('target_changed')
            if a.kind=='click' and (a.x is None or a.y is None):raise PermissionError('target_changed')
            if a.kind=='type' and (not a.text or len(a.text)>8000):raise ValueError('target_changed')
            if a.kind=='select' and not a.option:raise ValueError('target_changed')
            if a.kind=='hotkey':validate_hotkey(a.keys)
        if a.kind=='permanent_delete' and a.parameters.get('rollback_claim') not in (None,'irreversible'):raise ValueError('invalid_rollback_claim')
        if a.kind=='move_resize' and None in (a.x,a.y,a.width,a.height):raise ValueError('target_changed')

    def _ensure_tx(self,a):
        plan={'steps':[{'sequence':a.sequence,'kind':a.kind,'target':self._safe_params(a)}]};tx=self.transactions.transaction(a.transaction_id)
        if tx is None:tx,_=self.transactions.propose(a.transaction_id,self.binding,goal=f'W7.5 desktop/file action: {a.kind}',action_plan=plan)
        else:self.transactions.assert_binding(a.transaction_id,self.binding)
        if tx['state']=='proposed':tx=self.transactions.transition(a.transaction_id,'policy_check')
        return tx
    def _approval_state(self,txid):
        tx=self.transactions.transaction(txid)
        if tx and tx['state']=='policy_check':self.transactions.transition(txid,'approval_required')
    def _permit_state(self,txid):
        tx=self.transactions.transaction(txid)
        if tx['state'] in {'policy_check','approval_required'}:self.transactions.transition(txid,'permitted')
        elif tx['state']!='permitted':raise RuntimeError('recovery_review_required' if tx['state']=='recovery_review_required' else 'invalid_state')
    def _deny(self,a,before,reason):
        tx=self.transactions.transaction(a.transaction_id)
        if tx and tx['state'] in {'policy_check','approval_required','permitted'}:
            try:self.transactions.transition(a.transaction_id,'failed',error_code=reason)
            except Exception:pass
        return self._result(a,'blocked_by_policy',reason,before=before)
    def _cancel(self,a,reason):
        self._release_input();tx=self.transactions.transaction(a.transaction_id)
        if tx and tx['state'] not in {'completed','failed','cancelled','recovery_review_required'}:
            try:self.transactions.transition(a.transaction_id,'cancelled',error_code=reason)
            except Exception:pass
        return self._result(a,'cancelled' if reason=='cancelled' else 'blocked_by_policy',reason)
    def _recovery(self,txid,reason):
        tx=self.transactions.transaction(txid)
        if tx and tx['state'] in {'executing','verifying'}:
            try:self.transactions.transition(txid,'recovery_review_required',recovery_reason=reason)
            except Exception:pass
    def _release_input(self):
        try:self.desktop.release_input()
        except Exception:pass
    def _consequential(self,a):return a.kind not in self.READ_ONLY
    @staticmethod
    def _safe_params(a):
        d={'kind':a.kind,'window_id':a.window_id,'target_id':a.target_id,'x':a.x,'y':a.y,'width':a.width,'height':a.height,'amount':a.amount}
        if a.executable:d['executable']=str(Path(a.executable))
        for key,value in [('args_digest',a.args),('path_digest',a.path),('destination_digest',a.destination),('trash_root_digest',a.trash_root),('text_digest',a.text),('option_digest',a.option)]:
            if value:d[key]=digest(value)
        if a.keys:d['keys']=list(a.keys)
        for key in ('verified_visual_target_id','visual_target_digest','visual_observation_digest','destination'):
            if a.parameters.get(key):d[key]=str(a.parameters[key])
        return d
    @staticmethod
    def _target_identity(a):return a.window_id or a.destination or a.path or a.executable or a.target_id or a.kind
    @staticmethod
    def _safe_evidence(raw):return {k:v for k,v in (raw.items() if isinstance(raw,dict) else []) if k not in {'text','visible_text','content','clipboard_content'}}
    def _caller_result(self,a,raw):return dict(raw) if a.kind in {'read_file','read_ui'} else self._safe_evidence(raw)
    @staticmethod
    def _reason(exc):
        if isinstance(exc,TargetValidationError):return {'path_outside_allowed_root':'path_not_allowed','destination_not_allowed':'file_type_not_allowed'}.get(exc.reason_code,exc.reason_code)
        text=str(exc);known=('application_not_allowed','application_changed','executable_changed','window_changed','target_changed','path_not_allowed','path_changed','destination_exists','file_type_not_allowed','file_too_large','clipboard_access_blocked','clipboard_blocked','clipboard_changed','secret_transfer_blocked','reauthentication_required','approval_required','emergency_stop_active','verification_failed','recovery_review_required','unsupported_platform','insufficient_disk_space','checksum_mismatch')
        return next((k for k in known if k in text),'verification_failed')
    def _result(self,a,status,reason,before=None,after=None,result=None,rollback=None):return DesktopResult(status,reason,a.transaction_id,rollback or self.REVERSIBILITY.get(a.kind,'manual_recovery_only'),(before or {}).get('observation_id',''),(after or {}).get('observation_id',''),result or {})
