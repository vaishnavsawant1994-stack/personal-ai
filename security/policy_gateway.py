from __future__ import annotations
from dataclasses import dataclass,field
from enum import Enum
from pathlib import Path
import time
from typing import Any,Callable
from memory.policy import NEVER_STORE,normalize_storage_policy
from security.policy_store import PolicyStore,digest
from security.policy_targets import TargetValidationError,application_rule_matches,canonical_path,classify_clipboard,domain_rule_matches,normalize_origin,validate_file_metadata

class DecisionKind(str,Enum):
    ALLOW='allow';DENY='deny';APPROVAL_REQUIRED='approval_required';REAUTHENTICATION_REQUIRED='reauthentication_required';RECOVERY_REVIEW_REQUIRED='recovery_review_required'
@dataclass(frozen=True)
class PolicyOperation:
    operation:str;owner_id:str='owner';device_id:str|None=None;session_id:str|None=None;security_epoch:int=0;target_type:str='destination';target_identity:dict[str,Any]=field(default_factory=dict);application:dict[str,Any]|None=None;destination:str='';parameters:dict[str,Any]=field(default_factory=dict);data_classification:str='public';observation_id:str='';observation_digest:str='';outcome_state:str='not_dispatched'
    def parameter_digest(self)->str:return digest(self.parameters)
    def target_digest(self)->str:return digest({'target_type':self.target_type,'target_identity':self.target_identity,'destination':self.destination})
    def binding(self,policy_digest:str)->dict:return {'owner_id':self.owner_id,'device_id':self.device_id,'session_id':self.session_id,'security_epoch':int(self.security_epoch),'operation':self.operation,'target_digest':self.target_digest(),'parameter_digest':self.parameter_digest(),'data_classification':normalize_classification(self.data_classification),'application_digest':digest(self.application or {}),'destination':self.destination,'observation_id':self.observation_id,'observation_digest':self.observation_digest,'policy_digest':policy_digest}
    def trusted_action_binding(self,policy_digest:str,*,expires_at:float,max_uses:int)->dict:
        payload=self.binding(policy_digest);payload['expires_at']=float(expires_at);payload['maximum_uses']=max(1,int(max_uses));return payload
@dataclass(frozen=True)
class PolicyDecision:
    decision:DecisionKind;reason_code:str;explanation:str;policy_digest:str;policy_ids:tuple[str,...]=();policy_versions:tuple[int,...]=();max_uses:int=1
    @property
    def allowed(self)->bool:return self.decision is DecisionKind.ALLOW
    def safe_dict(self)->dict:return {'decision':self.decision.value,'reason_code':self.reason_code,'explanation':self.explanation,'policy_digest':self.policy_digest,'policy_ids':list(self.policy_ids),'policy_versions':list(self.policy_versions),'max_uses':self.max_uses}
_CLASS_LEVEL={'public':0,'personal':1,'sensitive':2,'secret':3,NEVER_STORE:4}
_EXTERNAL_TRANSFER={'external_upload','form_submission','email_send','message_send','share','public_publish','clipboard_transfer'}
_HIGH_RISK={'delete','destructive_delete','security_setting_modify','permission_change','purchase','financial_transfer','legal_acceptance','public_publish'}
_DURABLE_STORE={'local_file_write','download','memory_write','evidence_write'}
_STRONG_APPROVAL={'destructive_delete','purchase','financial_transfer','legal_acceptance','public_publish','permission_change','security_setting_modify'}
_EXPLANATIONS={'application_not_allowed':'This application is not in the owner-approved application policy.','application_changed':'The application identity changed after it was approved.','domain_not_allowed':'This website origin is not in the owner-approved domain policy.','redirect_not_allowed':'Navigation changed to an origin that is not explicitly permitted.','path_outside_allowed_root':'This file path is outside an owner-approved root or cannot be safely verified.','destination_not_allowed':'This destination is not explicitly allowed by owner policy.','sensitive_transfer_requires_approval':'Sensitive data transfer requires explicit owner approval.','secret_transfer_blocked':'Secret data is not permitted to leave an approved private boundary.','clipboard_access_blocked':'Clipboard access is not explicitly permitted by owner policy.','reauthentication_required':'Recent owner reauthentication is required for this action.','emergency_stop_active':'The owner Emergency Stop is active.','policy_changed':'The effective policy changed after authorization; approval must be obtained again.','recovery_review_required':'The system cannot safely determine the prior action outcome; owner review is required before retrying.','policy_not_found':'No owner policy permits this operation. Personal AI defaults to deny.','explicit_policy_deny':'An explicit owner deny policy blocks this operation.','device_session_mismatch':'The policy does not apply to this device or session.','approval_required':'This operation requires explicit owner approval.','allow':'The operation is permitted by the current owner policy.','never_store_blocked':'NEVER_STORE data cannot be written to durable memory or evidence.','clipboard_changed':'Clipboard contents changed after authorization; approval is no longer valid.'}
def normalize_classification(value:str)->str:
    normalized=normalize_storage_policy(value);normalized={'internal':'personal','private':'sensitive','neverstore':NEVER_STORE}.get(normalized,normalized);return normalized if normalized in _CLASS_LEVEL else 'personal'
class PolicyGateway:
    """Single W7.3 default-deny policy evaluation path. Execution stays in later W7 operators."""
    def __init__(self,path:str|Path,*,emergency_stop:Callable[[],bool]|None=None,security_epoch_provider:Callable[[],int]|None=None):self.store=PolicyStore(path);self._emergency_stop=emergency_stop or (lambda:False);self._security_epoch_provider=security_epoch_provider
    def schema_version(self)->int:return self.store.schema_version()
    def evaluate(self,operation:PolicyOperation,*,approved:bool=False,reauthenticated:bool=False,expected_policy_digest:str='',expected_clipboard_digest:str='',now:float|None=None)->PolicyDecision:
        ts=time.time() if now is None else float(now)
        if self._emergency_stop():return self._decision(operation,DecisionKind.DENY,'emergency_stop_active','')
        if operation.outcome_state in {'unknown','uncertain','dispatched_unverified'}:return self._decision(operation,DecisionKind.RECOVERY_REVIEW_REQUIRED,'recovery_review_required','')
        if not operation.owner_id or operation.security_epoch<0:return self._decision(operation,DecisionKind.DENY,'device_session_mismatch','')
        if self._security_epoch_provider is not None:
            try:current_epoch=int(self._security_epoch_provider())
            except Exception:current_epoch=operation.security_epoch
            if int(operation.security_epoch)!=current_epoch:return self._decision(operation,DecisionKind.DENY,'policy_changed','')
        classification=normalize_classification(operation.data_classification)
        if classification==NEVER_STORE and operation.operation in _DURABLE_STORE:return self._decision(operation,DecisionKind.DENY,'never_store_blocked','')
        if classification=='secret' and operation.operation in _EXTERNAL_TRANSFER:return self._decision(operation,DecisionKind.DENY,'secret_transfer_blocked','')
        validation=self._validate_target(operation,expected_clipboard_digest=expected_clipboard_digest)
        if validation:return self._decision(operation,DecisionKind.DENY,validation,'')
        effective=self.store.effective_policies(operation.owner_id,device_id=operation.device_id,session_id=operation.session_id,security_epoch=operation.security_epoch,now=ts);snapshot=self.store.snapshot_digest(effective)
        if expected_policy_digest and expected_policy_digest!=snapshot:return self._decision(operation,DecisionKind.DENY,'policy_changed',snapshot)
        app_matches=[];target_matches=[]
        for policy in effective:
            if policy['target_type']=='application' and operation.application:
                matched,_=application_rule_matches(policy['target_identity'],operation.application)
                if matched:app_matches.append(policy)
            if policy['target_type']==operation.target_type and self._policy_target_matches(policy,operation):target_matches.append(policy)
        if operation.application and not app_matches:return self._decision(operation,DecisionKind.DENY,'application_not_allowed',snapshot)
        matches=target_matches if operation.target_type!='application' else app_matches
        if not matches:return self._decision(operation,DecisionKind.DENY,self._missing_reason(operation.target_type),snapshot)
        combined=app_matches+[row for row in matches if row not in app_matches]
        for policy in combined:
            if operation.operation in policy['denied_operations'] or '*' in policy['denied_operations']:return self._decision(operation,DecisionKind.DENY,'explicit_policy_deny',snapshot,combined)
        allowing=[row for row in matches if operation.operation in row['allowed_operations'] or '*' in row['allowed_operations']]
        if operation.application:
            app_allowing=[row for row in app_matches if operation.operation in row['allowed_operations'] or 'control' in row['allowed_operations'] or '*' in row['allowed_operations']]
            if not app_allowing:return self._decision(operation,DecisionKind.DENY,'application_not_allowed',snapshot,combined)
            combined=app_allowing+[row for row in allowing if row not in app_allowing]
        else:combined=allowing
        if not allowing:return self._decision(operation,DecisionKind.DENY,self._missing_reason(operation.target_type),snapshot,matches)
        max_level=max((_CLASS_LEVEL.get(normalize_classification(item),99) for row in combined for item in row['sensitivity_restrictions']),default=99)
        if max_level!=99 and _CLASS_LEVEL[classification]>max_level:
            reason='secret_transfer_blocked' if classification=='secret' else 'sensitive_transfer_requires_approval';kind=DecisionKind.DENY if classification=='secret' else DecisionKind.APPROVAL_REQUIRED;return self._decision(operation,kind,reason,snapshot,combined)
        requires_reauth=operation.operation in _HIGH_RISK or any(row['reauth_rule'] in {'always','high_risk'} for row in combined)
        if requires_reauth and not reauthenticated:return self._decision(operation,DecisionKind.REAUTHENTICATION_REQUIRED,'reauthentication_required',snapshot,combined)
        requires_approval=(operation.operation in _STRONG_APPROVAL or (classification=='sensitive' and operation.operation in _EXTERNAL_TRANSFER) or any(row['approval_rule'] in {'always','strong'} for row in combined) or any(row['approval_rule']=='sensitive_external' for row in combined) and classification=='sensitive' and operation.operation in _EXTERNAL_TRANSFER or any(row['approval_rule']=='destructive' for row in combined) and operation.operation in {'delete','destructive_delete'})
        if requires_approval and not approved:
            reason='sensitive_transfer_requires_approval' if classification=='sensitive' and operation.operation in _EXTERNAL_TRANSFER else 'approval_required';return self._decision(operation,DecisionKind.APPROVAL_REQUIRED,reason,snapshot,combined)
        return self._decision(operation,DecisionKind.ALLOW,'allow',snapshot,combined)
    def issue_temporary_permit(self,operation:PolicyOperation,decision:PolicyDecision,*,ttl_seconds:int=120)->dict:
        if decision.decision is not DecisionKind.ALLOW:raise PermissionError('policy decision is not allow')
        return self.store.issue_permit(policy_digest=decision.policy_digest,binding=operation.binding(decision.policy_digest),owner_id=operation.owner_id,device_id=operation.device_id,session_id=operation.session_id,security_epoch=operation.security_epoch,operation=operation.operation,ttl_seconds=ttl_seconds,max_uses=max(1,decision.max_uses))
    def consume_temporary_permit(self,permit_id:str,operation:PolicyOperation,decision:PolicyDecision)->bool:
        ok=self.store.consume_permit(permit_id,binding=operation.binding(decision.policy_digest),owner_id=operation.owner_id,device_id=operation.device_id,session_id=operation.session_id,security_epoch=operation.security_epoch,policy_digest=decision.policy_digest)
        if ok:self.store.increment_use(list(decision.policy_ids))
        return ok
    def mark_unknown_outcome(self,permit_id:str,reason:str='unknown_outcome')->None:self.store.mark_recovery_review(permit_id,reason)
    def add_policy(self,**kwargs)->dict:return self.store.upsert_policy(**kwargs)
    def revoke_policy(self,policy_id:str,**kwargs)->bool:return self.store.revoke_policy(policy_id,**kwargs)
    def set_policy_active(self,policy_id:str,**kwargs)->bool:return self.store.set_policy_active(policy_id,**kwargs)
    def reset_to_safe_defaults(self,owner_id:str,**kwargs)->int:return self.store.reset_owner(owner_id,**kwargs)
    def trusted_action_binding(self,operation:PolicyOperation,decision:PolicyDecision,*,expires_at:float|None=None)->dict:return operation.trusted_action_binding(decision.policy_digest,expires_at=float(expires_at if expires_at is not None else time.time()+120),max_uses=decision.max_uses)
    def owner_snapshot(self,owner_id:str)->dict:return {'policies':self.store.list_policies(owner_id,include_inactive=True),'recent_use':self.store.recent_audit(owner_id,50),'safe_default':'deny','schema_version':self.store.schema_version()}
    def _validate_target(self,operation:PolicyOperation,*,expected_clipboard_digest:str)->str|None:
        try:
            if operation.target_type=='domain':normalize_origin(operation.destination or operation.target_identity.get('url',''),allow_ip_literal=bool(operation.target_identity.get('allow_ip_literal',False)),allow_private_network=bool(operation.target_identity.get('allow_private_network',False)))
            elif operation.target_type=='path':
                roots=list(operation.target_identity.get('approved_roots') or [])
                if not roots:return 'path_outside_allowed_root'
                canonical_path(str(operation.target_identity.get('path') or operation.destination),roots,allow_network=bool(operation.target_identity.get('allow_network',False)),path_is_reparse=bool(operation.target_identity.get('path_is_reparse',False)),path_is_mounted=bool(operation.target_identity.get('path_is_mounted',False)),allow_mounted=bool(operation.target_identity.get('allow_mounted',False)))
                file_path=operation.target_identity.get('file_for_validation')
                if file_path:validate_file_metadata(str(file_path),claimed_mime=str(operation.target_identity.get('claimed_mime') or ''),max_bytes=int(operation.target_identity.get('max_bytes') or 50*1024*1024))
            elif operation.target_type=='clipboard':
                content=operation.parameters.get('clipboard_content')
                if content is not None:
                    meta=classify_clipboard(content,max_bytes=int(operation.target_identity.get('max_bytes') or 64*1024))
                    if meta['secret'] and operation.operation=='clipboard_transfer':return 'secret_transfer_blocked'
                    if expected_clipboard_digest and expected_clipboard_digest!=meta['sha256']:return 'clipboard_changed'
            elif operation.target_type=='application' and not operation.application:return 'application_not_allowed'
        except TargetValidationError as exc:return exc.reason_code
        return None
    def _policy_target_matches(self,policy:dict,operation:PolicyOperation)->bool:
        rule=policy['target_identity']
        try:
            if operation.target_type=='domain':return domain_rule_matches(rule,operation.destination or operation.target_identity.get('url',''))[0]
            if operation.target_type=='application':return application_rule_matches(rule,operation.application or operation.target_identity)[0]
            if operation.target_type=='path':
                root=str(rule.get('root') or '');candidate=str(operation.target_identity.get('path') or operation.destination)
                if not root:return False
                canonical_path(candidate,[root],allow_network=bool(rule.get('allow_network',False)),path_is_reparse=bool(operation.target_identity.get('path_is_reparse',False)),path_is_mounted=bool(operation.target_identity.get('path_is_mounted',False)),allow_mounted=bool(rule.get('allow_mounted',False)));return True
            if operation.target_type=='clipboard':
                expected=str(rule.get('destination') or '');actual=str(operation.destination or operation.target_identity.get('destination') or '');return not expected or expected==actual
            expected=str(rule.get('identity') or rule.get('destination') or '');actual=str(operation.destination or operation.target_identity.get('identity') or '');return bool(expected and expected==actual)
        except TargetValidationError:return False
    @staticmethod
    def _missing_reason(target_type:str)->str:return {'application':'application_not_allowed','domain':'domain_not_allowed','path':'path_outside_allowed_root','clipboard':'clipboard_access_blocked'}.get(target_type,'destination_not_allowed')
    def _decision(self,operation:PolicyOperation,kind:DecisionKind,reason_code:str,policy_digest:str,policies:list[dict]|None=None)->PolicyDecision:
        rows=list(policies or []);maximum=min((int(row['max_uses']) for row in rows if row.get('max_uses') is not None),default=1);decision=PolicyDecision(kind,reason_code,_EXPLANATIONS.get(reason_code,'The operation was blocked by owner policy.'),policy_digest,tuple(row['policy_id'] for row in rows),tuple(int(row['version']) for row in rows),max(1,maximum));self.store.audit_decision(owner_id=operation.owner_id,decision=kind.value,reason_code=reason_code,target_digest=operation.target_digest(),operation=operation.operation,policy_digest=policy_digest,details={'device_id':operation.device_id,'session_id_present':bool(operation.session_id),'classification':normalize_classification(operation.data_classification)});return decision
