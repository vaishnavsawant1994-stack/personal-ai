from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from recovery.operator_recovery import RecoveryAuthority, VerificationRecord


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


class CrossOperatorOrchestrator:
    """Bounded W7.6 orchestrator over existing W7.4/W7.5 execution surfaces.

    It never performs browser/desktop/file/clipboard actions itself. The provided operator
    remains the sole executor. W7.6 records dispatch/verification/recovery around it.
    """
    def __init__(self,recovery:RecoveryAuthority,*,worker_id:str='w76-orchestrator'):
        self.recovery=recovery;self.worker_id=worker_id

    def execute_step(self,operator,action,*,operation_class:str,target:str='',destination:str='',approved:bool=False,reauthenticated:bool=False,precondition:dict|None=None,expected_postcondition:dict|None=None,evidence_refs:list[str]|None=None):
        txid=str(action.transaction_id);action_id=f'{txid}:{int(action.sequence)}'
        lease=self.recovery.acquire_lease(txid,self.worker_id,ttl_seconds=45)
        idempotency=_digest({'tx':txid,'action':action_id,'operation_class':operation_class,'target':target,'destination':destination})
        dispatch=self.recovery.begin_dispatch(txid,action_id,operation_class=operation_class,target=target,destination=destination,idempotency_key=idempotency,worker_id=self.worker_id,fencing_token=lease['fencing_token'])
        if dispatch['state'] not in {'dispatching'}:
            self.recovery.release_lease(txid,self.worker_id,lease['fencing_token'])
            return {'status':'recovery_review_required','reason_code':'duplicate_dispatch_uncertain','dispatch_id':dispatch['dispatch_id']}
        try:
            self.recovery.mark_dispatched(dispatch['dispatch_id'],worker_id=self.worker_id,fencing_token=lease['fencing_token'])
            try:result=operator.execute(action,approved=approved,reauthenticated=reauthenticated)
            except TypeError:result=operator.execute(action)
            payload=result.__dict__ if hasattr(result,'__dict__') else dict(result or {})
            outcome=self._map_result(payload)
            observed={'status':payload.get('status',''),'reason_code':payload.get('reason_code',''),'result':payload.get('result',{})}
            refs=tuple(evidence_refs or self._refs(payload))
            material={'references':list(refs),'precondition':precondition or {},'expected':expected_postcondition or {},'observed':observed}
            record=VerificationRecord(transaction_id=txid,action_id=action_id,dispatch_id=dispatch['dispatch_id'],idempotency_key=idempotency,operation_class=operation_class,target=target,destination=destination,precondition=precondition or {},expected_postcondition=expected_postcondition or {},observed_postcondition=observed,verifier_identity='w76.cross_operator',verifier_version='1',evidence_references=refs,evidence_checksum=_digest(material),verification_timestamp=time.time(),verification_fresh_until=time.time()+120,result=outcome,explanation=self._explanation(outcome),confidence=1.0 if outcome in {'verified_success','verified_no_effect','verified_failure'} else None)
            verification=self.recovery.record_verification(record)
            return {**payload,'w76_verification':verification,'dispatch_id':dispatch['dispatch_id']}
        finally:self.recovery.release_lease(txid,self.worker_id,lease['fencing_token'])

    @staticmethod
    def _map_result(payload:dict)->str:
        status=str(payload.get('status') or '');reason=str(payload.get('reason_code') or '')
        if status in {'completed','verified'}:return 'verified_success'
        if status in {'blocked_by_policy','approval_required','reauthentication_required'}:return 'blocked_before_dispatch'
        if status=='cancelled':return 'cancelled_before_dispatch'
        if status in {'recovery_review_required','unknown_outcome'}:return 'unknown_outcome'
        if status in {'partial','partially_completed'}:return 'verified_partial'
        if status in {'failed','verification_failed'}:
            if reason in {'no_effect','verified_no_effect'}:return 'verified_no_effect'
            return 'verified_failure'
        return 'unknown_outcome'

    @staticmethod
    def _refs(payload:dict)->list[str]:
        refs=[]
        for key in ('before_observation_id','after_observation_id'):
            value=str(payload.get(key) or '')
            if value:refs.append(value)
        result=payload.get('result') or {}
        value=str(result.get('evidence_ref') or '')
        if value:refs.append(value[:500])
        file_path=str(result.get('file_path') or '')
        if file_path:refs.append('file-path-digest:'+hashlib.sha256(file_path.encode('utf-8')).hexdigest())
        download_name=str(result.get('download_name') or '')
        if download_name:refs.append('download-name-digest:'+hashlib.sha256(download_name.encode('utf-8')).hexdigest())
        return refs

    @staticmethod
    def _explanation(result:str)->str:
        return {'verified_success':'The expected postcondition was independently observed.','verified_no_effect':'Verification established that the attempted action produced no side effect.','verified_partial':'Only part of the expected postcondition was observed. Recovery review is required.','verified_failure':'Verification established that the expected postcondition was not achieved.','unknown_outcome':'The action may have been dispatched, but evidence cannot establish the real-world outcome.','cancelled_before_dispatch':'The action was cancelled before dispatch.','blocked_before_dispatch':'Governance blocked the action before dispatch.','recovery_review_required':'Owner recovery review is required before any further side effect.'}[result]

    def recover_after_crash(self,transaction_id:str,action_id:str,read_only_verifier,*,worker_id:str|None=None):
        """Read-only recovery verification. It never retries the side effect."""
        worker=worker_id or f'{self.worker_id}-recovery';lease=self.recovery.acquire_lease(transaction_id,worker,ttl_seconds=45)
        try:
            latest=self.recovery.latest_verification(transaction_id,action_id)
            if latest and latest['result']=='verified_success':return {'state':'verified_success','resume_safe':True}
            observed=read_only_verifier()
            if not isinstance(observed,dict):observed={'observed':bool(observed)}
            result=str(observed.get('verification_result') or 'unknown_outcome')
            if result not in {'verified_success','verified_no_effect','verified_partial','verified_failure'}:result='unknown_outcome'
            self.recovery.set_state(transaction_id,'verified_no_effect' if result=='verified_no_effect' else ('verified_success' if result=='verified_success' else 'recovery_review_required'),reason=result)
            return {'state':self.recovery.recovery(transaction_id)['state'],'resume_safe':result in {'verified_success','verified_no_effect'},'retry_safe':result=='verified_no_effect'}
        finally:self.recovery.release_lease(transaction_id,worker,lease['fencing_token'])

    def browser_download_recipe(self,*,origin:str,filename:str,mime:str,checksum:str,approved_folder:str)->dict:return {'steps':['validate_origin','validate_filename_mime','download_via_w7.4','checksum_file','store_in_approved_folder','verify_completion'],'origin':origin,'filename':filename,'mime':mime,'checksum':checksum,'approved_folder':approved_folder}
    def file_application_recipe(self,*,file_path:str,application_identity:str)->dict:return {'steps':['validate_file_policy','open_via_w7.5','verify_window','perform_bounded_action','save_output','verify_output_checksum_or_version'],'file_path':file_path,'application_identity':application_identity}
    def knowledge_upload_recipe(self,*,file_path:str,origin:str)->dict:return {'steps':['inspect_through_knowledge','create_derived_output','verify_local_output','request_trusted_action_approval','upload_via_w7.4','verify_uploaded_resource'],'file_path':file_path,'origin':origin}
    def extraction_report_recipe(self,*,origin:str,report_path:str)->dict:return {'steps':['extract_via_w7.4','sanitize_untrusted_content','create_local_report_via_w7.5','verify_report','stop_before_external_share_without_approval'],'origin':origin,'report_path':report_path}
