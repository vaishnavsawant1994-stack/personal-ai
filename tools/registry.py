from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
import sqlite3
from typing import Any, Callable
from urllib.parse import urlparse
from core.permissions import PermissionDecision, PermissionEngine
from desktop.operator_context import current_operator_request

class Risk(IntEnum): READ_ONLY=0; REVERSIBLE=1; EXTERNAL_SIDE_EFFECT=2; DESTRUCTIVE=3; CRITICAL=4
@dataclass(frozen=True)
class VerificationResult:
    verified: bool; reason: str; evidence: dict[str,Any]
@dataclass
class Tool:
    name:str; description:str; handler:Callable[[dict[str,Any]],Any]; risk:Risk=Risk.READ_ONLY
    verifier:Callable[[dict[str,Any],Any],Any]|None=None; rollback:Callable[[dict[str,Any],Any],Any]|None=None; rollback_description:str=''
    allowed_destinations:tuple[str,...]|None=None; verification_required:bool=False; requires_reauth:bool=False
    connector_id:str|None=None; capability:str|None=None; minimum_risk:Risk|None=None; prohibited_data_classifications:tuple[str,...]=(); prohibited:bool=False
    prepare:Callable[[dict[str,Any]],dict[str,Any]]|None=None; on_reject:Callable[[dict[str,Any]],Any]|None=None; requires_trusted_context:bool=False
class ToolRegistry:
    def __init__(self,settings):
        self.settings=settings; self.permissions=PermissionEngine(settings.autonomy_mode); self._tools={}; self.emergency_stop=False; self._control_path=None; self._approval_path=None; self.policy_gateway=None; self.recovery_authority=None; self._data_root=None
        data_dir=getattr(settings,'data_dir',None)
        if data_dir is not None:self.bind_data_root(data_dir)
    def bind_data_root(self,data_dir):
        data_root=Path(data_dir)
        if self._data_root is not None and self._data_root!=data_root:raise RuntimeError('tool registry data root is already bound')
        if self._data_root is not None:return self._data_root
        self._data_root=data_root;self._control_path=data_root/'runtime-controls.sqlite3';self._approval_path=data_root/'trusted-actions.sqlite3';self._control_path.parent.mkdir(parents=True,exist_ok=True)
        with self._control_con() as con:
            con.execute('CREATE TABLE IF NOT EXISTS runtime_controls (key TEXT PRIMARY KEY,value TEXT NOT NULL)');row=con.execute("SELECT value FROM runtime_controls WHERE key='emergency_stop'").fetchone();self.emergency_stop=bool(row and row[0]=='1')
        from security.approvals import ApprovalManager
        from security.policy_gateway import PolicyGateway
        self.policy_gateway=PolicyGateway(data_root/'operator-policies.sqlite3',emergency_stop=lambda:self.emergency_stop,security_epoch_provider=lambda:ApprovalManager(path=self._approval_path).current_security_epoch())
        return data_root
    def _control_con(self):return sqlite3.connect(self._control_path)
    def current_security_epoch(self):
        if self._approval_path is None:return 0
        from security.approvals import ApprovalManager
        return ApprovalManager(path=self._approval_path).current_security_epoch()
    def ensure_recovery_authority(self):
        if self.recovery_authority is not None:return self.recovery_authority
        if self._data_root is None:raise RuntimeError('recovery authority requires local data directory')
        from recovery.recovery_authority import DurableRecoveryAuthority
        self.recovery_authority=DurableRecoveryAuthority(self._data_root/'operator-transactions.sqlite3',emergency_stop=lambda:self.emergency_stop,policy_gateway=self.policy_gateway,security_epoch_provider=self.current_security_epoch)
        return self.recovery_authority
    def set_emergency_stop(self,enabled:bool):
        previous=self.emergency_stop;self.emergency_stop=bool(enabled)
        if self._control_path is not None:
            with self._control_con() as con:con.execute("INSERT OR REPLACE INTO runtime_controls(key,value) VALUES('emergency_stop',?)",('1' if enabled else '0',))
        if self.emergency_stop and not previous and self._approval_path is not None and self._approval_path.exists():
            from security.approvals import ApprovalManager;ApprovalManager(path=self._approval_path).advance_security_epoch()
        if self.emergency_stop and not previous and self.recovery_authority is not None:self.recovery_authority.emergency_stop_snapshot()
        return self.emergency_stop
    def evaluate_policy(self,operation,**kwargs):
        if self.policy_gateway is None:raise PermissionError('policy gateway is unavailable; default deny')
        return self.policy_gateway.evaluate(operation,**kwargs)
    def policy_snapshot(self,owner_id='owner'):
        if self.policy_gateway is None:return {'policies':[],'recent_use':[],'safe_default':'deny','schema_version':None}
        return self.policy_gateway.owner_snapshot(owner_id)
    def recovery_snapshot(self,transaction_id):return self.ensure_recovery_authority().owner_view(transaction_id)
    def register(self,tool:Tool):
        if tool.name in self._tools:raise ValueError(f'Duplicate tool {tool.name}')
        if tool.minimum_risk is not None and int(tool.risk)<int(tool.minimum_risk):tool.risk=Risk(int(tool.minimum_risk))
        self._tools[tool.name]=tool
    def get(self,name):return self._tools[name]
    def all(self):return list(self._tools.values())
    def schema_text(self):return '\n'.join(f'- {t.name}: {t.description}; risk={t.risk.name}' for t in self._tools.values() if not t.prohibited)
    def set_autonomy_mode(self,mode):
        mode=str(mode).lower().strip()
        if mode not in {'observe','suggest','ask','act'}:raise ValueError('invalid autonomy mode')
        self.permissions.mode=mode;return mode
    @property
    def autonomy_mode(self):return self.permissions.mode
    @staticmethod
    def destination(parameters):
        params=parameters or {};sid=params.get('spreadsheet_id');rng=params.get('range')
        if sid not in (None,'') and rng not in (None,''):return f'{str(sid)[:500]}#{str(rng)[:500]}'
        fid=params.get('file_id');parent=params.get('parent_id');filename=params.get('filename')
        if fid not in (None,''):return f'file:{str(fid)[:800]}'
        if filename not in (None,'') and parent not in (None,''):return f'parent:{str(parent)[:500]}/name:{str(filename)[:400]}'
        event=params.get('event')
        if isinstance(event,dict) and event.get('attendees'):
            emails=[str(x.get('email','')) for x in event['attendees'] if isinstance(x,dict) and x.get('email')]
            if emails:return ','.join(emails)[:1000]
        for key in ('destination','recipient','recipients','to','email','emails','url','domain','path','file_path','filename','channel','room','calendar_id','spreadsheet_id','document_id','repository'):
            value=params.get(key)
            if value in (None,'',[],{}):continue
            if isinstance(value,(list,tuple,set)):return ','.join(str(x) for x in value)[:1000]
            if isinstance(value,dict):return str(sorted(value.items()))[:1000]
            return str(value)[:1000]
        return ''
    @staticmethod
    def _destination_host(destination):
        value=str(destination or '').strip().lower()
        if not value:return ''
        if '@' in value and '://' not in value:return value.rsplit('@',1)[-1]
        parsed=urlparse(value if '://' in value else f'https://{value}');return (parsed.hostname or value).lower()
    def validate_destination(self,tool,parameters):
        if not tool.allowed_destinations:return
        host=self._destination_host(self.destination(parameters));allowed=tuple(str(x).strip().lower() for x in tool.allowed_destinations if str(x).strip())
        if not host or not any(host==x or host.endswith('.'+x) for x in allowed):raise PermissionError('destination is outside the configured allowlist')
    def effective_risk(self,tool,*,parameters=None,data_classification='internal'):
        risk=Risk(int(tool.risk))
        if tool.minimum_risk is not None:risk=max(risk,Risk(int(tool.minimum_risk)))
        destination=self.destination(parameters);classification=str(data_classification or 'internal').strip().lower()
        if destination and classification=='secret':risk=max(risk,Risk.CRITICAL)
        elif destination and classification in {'sensitive','restricted'}:risk=max(risk,Risk.DESTRUCTIVE)
        return Risk(int(risk))
    def _prepare_trusted(self,tool,parameters):
        if not tool.requires_trusted_context:return parameters
        if not isinstance(parameters,dict):raise PermissionError('trusted operator parameters are required')
        context=current_operator_request()
        if context is None:raise PermissionError('trusted browser/session context is required for computer control')
        parameters.pop('_trusted_context',None);parameters['_trusted_context']=context.safe_dict()
        if tool.prepare is not None and not parameters.get('_personal_ai_prepared'):
            prepared=tool.prepare(parameters)
            if not isinstance(prepared,dict):raise RuntimeError('trusted tool preparation must return parameters')
            parameters.clear();parameters.update(prepared);parameters['_personal_ai_prepared']=True
        return parameters
    def automatic(self,tool):return self.authorize(tool,confirmed=False).allowed
    def authorize(self,tool,confirmed=False,*,parameters=None,data_classification='internal'):
        if self.emergency_stop:return PermissionDecision(False,False,'owner emergency stop is active')
        if tool.prohibited:return PermissionDecision(False,False,'this connector operation is prohibited by policy')
        parameters=self._prepare_trusted(tool,parameters);classification=str(data_classification or 'internal').strip().lower()
        if classification in set(tool.prohibited_data_classifications):return PermissionDecision(False,False,'this data classification is prohibited for the connector operation')
        self.validate_destination(tool,parameters);risk=self.effective_risk(tool,parameters=parameters,data_classification=classification);return self.permissions.decide(int(risk),confirmed=confirmed)
    def verify_result(self,tool,parameters,result):
        if tool.verifier is not None:
            verdict=tool.verifier(parameters,result)
            if isinstance(verdict,VerificationResult):verification=verdict
            elif isinstance(verdict,dict):verification=VerificationResult(bool(verdict.get('verified')),str(verdict.get('reason') or ('verified' if verdict.get('verified') else 'verification failed')),dict(verdict.get('evidence') or {}))
            else:verification=VerificationResult(bool(verdict),'custom verification contract',{})
        elif isinstance(result,dict) and result.get('verified') is True:verification=VerificationResult(True,'tool returned explicit verification evidence',dict(result))
        elif tool.risk==Risk.READ_ONLY:verification=VerificationResult(True,'read-only handler returned observed data',{})
        else:verification=VerificationResult(False,'no result verification contract is configured for this side-effecting tool',{})
        if tool.verification_required and not verification.verified:raise RuntimeError(f'tool result verification failed: {verification.reason}')
        return verification
    @staticmethod
    def rollback_metadata(tool):return {'available':callable(tool.rollback),'description':str(tool.rollback_description or '')}
