from __future__ import annotations

from dataclasses import dataclass, field, asdict

SCHEMA_VERSION = 1
HEALTH_STATES = {
    'healthy','disconnected','authentication_required','authentication_expired','insufficient_scope',
    'permission_denied','rate_limited','degraded','timeout','provider_unavailable','invalid_response',
    'verification_failed','revocation_pending','disabled','not_configured','revoked','quota_exceeded',
}
RISK_ORDER = {'read_only':0,'reversible':1,'external_side_effect':2,'destructive':3,'critical':4,'prohibited':5}
EFFECTS = {'read','write','consequential','destructive','prohibited'}
APPROVALS = {'none','policy','required','prohibited'}

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 4.0
    jitter: bool = True
    retry_statuses: tuple[int,...] = (429,500,502,503,504)
    def validate(self):
        if not 1 <= int(self.max_attempts) <= 10: raise ValueError('retry max_attempts must be 1..10')
        if not 0 <= float(self.base_delay_seconds) <= 30: raise ValueError('retry base delay is invalid')
        if not float(self.base_delay_seconds) <= float(self.max_delay_seconds) <= 300: raise ValueError('retry max delay is invalid')

@dataclass(frozen=True)
class PaginationPolicy:
    supported: bool = False
    cursor_field: str = 'nextPageToken'
    max_pages: int = 10
    max_items: int = 1000
    def validate(self):
        if not 1 <= int(self.max_pages) <= 100: raise ValueError('pagination max_pages must be 1..100')
        if not 1 <= int(self.max_items) <= 10000: raise ValueError('pagination max_items must be 1..10000')
        if self.supported and not str(self.cursor_field).strip(): raise ValueError('pagination cursor_field is required')

@dataclass(frozen=True)
class RateLimitPolicy:
    respects_retry_after: bool = True
    max_retry_after_seconds: int = 60
    requests_per_minute: int | None = None
    def validate(self):
        if not 1 <= int(self.max_retry_after_seconds) <= 3600: raise ValueError('max_retry_after_seconds is invalid')
        if self.requests_per_minute is not None and not 1 <= int(self.requests_per_minute) <= 100000: raise ValueError('requests_per_minute is invalid')

@dataclass(frozen=True)
class ConnectorOperation:
    name: str
    effect: str
    risk: str
    approval: str = 'policy'
    requires_reauth: bool = False
    required_scopes: tuple[str,...] = ()
    allowed_data_classifications: tuple[str,...] = ('public','internal')
    prohibited_data_classifications: tuple[str,...] = ('secret',)
    destination_types: tuple[str,...] = ()
    pagination: PaginationPolicy = field(default_factory=PaginationPolicy)
    rate_limit: RateLimitPolicy = field(default_factory=RateLimitPolicy)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    idempotency_supported: bool = False
    verification_supported: bool = False
    rollback_available: bool = False
    prohibited: bool = False
    def validate(self):
        if not self.name or '.' not in self.name: raise ValueError('operation name must be namespaced')
        if self.effect not in EFFECTS: raise ValueError(f'invalid operation effect: {self.effect}')
        if self.risk not in RISK_ORDER: raise ValueError(f'invalid operation risk: {self.risk}')
        if self.approval not in APPROVALS: raise ValueError(f'invalid approval requirement: {self.approval}')
        allowed=set(self.allowed_data_classifications); prohibited=set(self.prohibited_data_classifications)
        if allowed & prohibited: raise ValueError('data classifications cannot be both allowed and prohibited')
        if self.prohibited and self.approval != 'prohibited': raise ValueError('prohibited operation must use prohibited approval')
        self.pagination.validate(); self.rate_limit.validate(); self.retry.validate()

@dataclass(frozen=True)
class ConnectorManifest:
    connector_id: str
    display_name: str
    provider: str
    schema_version: int
    authentication_type: str
    required_oauth_scopes: tuple[str,...] = ()
    optional_oauth_scopes: tuple[str,...] = ()
    operations: tuple[ConnectorOperation,...] = ()
    allowed_data_classifications: tuple[str,...] = ('public','internal')
    prohibited_data_classifications: tuple[str,...] = ('secret',)
    webhook_capabilities: tuple[str,...] = ()
    token_revocation_supported: bool = False
    healthcheck_operation: str | None = None
    configuration_requirements: tuple[str,...] = ()
    read_only: bool = False
    scope_reasons: tuple[tuple[str,str],...] = ()
    content_limits: tuple[tuple[str,int],...] = ()
    supported_content_types: tuple[str,...] = ()
    def validate(self):
        if self.schema_version != SCHEMA_VERSION: raise ValueError(f'unsupported connector schema version: {self.schema_version}')
        if not self.connector_id or not self.connector_id.replace('_','').replace('-','').isalnum(): raise ValueError('invalid connector id')
        if not self.display_name.strip() or not self.provider.strip(): raise ValueError('connector display name/provider required')
        if self.authentication_type not in {'oauth2_pkce','bearer_token','none'}: raise ValueError('unsupported authentication type')
        if not self.operations: raise ValueError('connector must declare operations')
        names=set()
        for op in self.operations:
            op.validate()
            if op.name in names: raise ValueError(f'duplicate connector operation: {op.name}')
            if not op.name.startswith(self.connector_id+'.'): raise ValueError('operation namespace must match connector id')
            if self.read_only and op.effect != 'read': raise ValueError('read-only connector cannot declare write effects')
            names.add(op.name)
        if self.healthcheck_operation and self.healthcheck_operation not in names: raise ValueError('healthcheck operation is not declared')
        if set(self.required_oauth_scopes) & set(self.optional_oauth_scopes): raise ValueError('OAuth scope cannot be both required and optional')
        if set(self.allowed_data_classifications) & set(self.prohibited_data_classifications): raise ValueError('manifest data classification conflict')
        declared=set(self.required_oauth_scopes)|set(self.optional_oauth_scopes)
        reasons={scope for scope,_ in self.scope_reasons}
        if reasons and reasons != declared: raise ValueError('every declared OAuth scope must have exactly one reason')
        if any(not str(reason).strip() for _,reason in self.scope_reasons): raise ValueError('OAuth scope reason is required')
        if any(int(v)<=0 for _,v in self.content_limits): raise ValueError('content limits must be positive')
        return self
    def operation(self, name: str) -> ConnectorOperation:
        for op in self.operations:
            if op.name == name: return op
        raise KeyError(name)
    def safe_dict(self): return asdict(self)
    def limit(self,name:str,default=None):
        return dict(self.content_limits).get(name,default)

class ConnectorManifestRegistry:
    def __init__(self): self._items: dict[str,ConnectorManifest] = {}
    def register(self, manifest: ConnectorManifest):
        manifest.validate()
        if manifest.connector_id in self._items: raise ValueError(f'duplicate connector id: {manifest.connector_id}')
        self._items[manifest.connector_id]=manifest
        return manifest
    def get(self, connector_id: str): return self._items[connector_id]
    def list(self): return list(self._items.values())

def _op(name,effect,risk,*,approval='policy',reauth=False,scopes=(),allowed=('public','internal'),prohibited=('secret',),dest=(),page=False,idem=False,verify=False,rollback=False,disabled=False,max_pages=10,max_items=1000):
    return ConnectorOperation(name,effect,risk,approval,reauth,tuple(scopes),tuple(allowed),tuple(prohibited),tuple(dest),PaginationPolicy(page,max_pages=max_pages,max_items=max_items),RateLimitPolicy(),RetryPolicy(),idem,verify,rollback,disabled)

def gmail_manifest():
    ro=('https://www.googleapis.com/auth/gmail.readonly',); send=('https://www.googleapis.com/auth/gmail.send',); modify=('https://www.googleapis.com/auth/gmail.modify',)
    return ConnectorManifest('gmail','Gmail','google',1,'oauth2_pkce',ro,send+modify,(
        _op('gmail.read','read','read_only',approval='none',scopes=ro,page=True),
        _op('gmail.search','read','read_only',approval='none',scopes=ro,page=True),
        _op('gmail.draft','write','reversible',approval='policy',scopes=('https://www.googleapis.com/auth/gmail.compose',),idem=True,verify=True,rollback=True),
        _op('gmail.send','consequential','external_side_effect',approval='required',scopes=send,dest=('email',),idem=False,verify=True),
        _op('gmail.modify','write','reversible',approval='policy',scopes=modify,idem=True,verify=True,rollback=True),
        _op('gmail.delete','prohibited','prohibited',approval='prohibited',reauth=True,scopes=('https://mail.google.com/',),disabled=True),
    ), token_revocation_supported=True, healthcheck_operation='gmail.read', configuration_requirements=('google_client_id',))

def calendar_manifest():
    scope=('https://www.googleapis.com/auth/calendar',); read=('https://www.googleapis.com/auth/calendar.readonly',)
    return ConnectorManifest('calendar','Google Calendar','google',1,'oauth2_pkce',read,scope,(
        _op('calendar.read','read','read_only',approval='none',scopes=read,page=True),
        _op('calendar.search','read','read_only',approval='none',scopes=read,page=True),
        _op('calendar.create','consequential','external_side_effect',approval='required',scopes=scope,dest=('calendar','attendee'),idem=True,verify=True,rollback=True),
        _op('calendar.update','consequential','external_side_effect',approval='required',scopes=scope,dest=('calendar','attendee'),idem=True,verify=True),
        _op('calendar.delete','destructive','destructive',approval='required',reauth=True,scopes=scope,dest=('calendar',),idem=True,verify=True),
    ), token_revocation_supported=True, healthcheck_operation='calendar.read', configuration_requirements=('google_client_id',))

def drive_manifest():
    read_scope=('https://www.googleapis.com/auth/drive.readonly',)
    write_scope=('https://www.googleapis.com/auth/drive.file',)
    ops=(
        _op('drive.files.list','read','read_only',approval='none',scopes=read_scope,page=True,max_pages=10,max_items=1000),
        _op('drive.files.search','read','read_only',approval='none',scopes=read_scope,page=True,max_pages=10,max_items=1000),
        _op('drive.files.metadata','read','read_only',approval='none',scopes=read_scope),
        _op('drive.files.read','read','read_only',approval='none',scopes=read_scope),
        _op('drive.files.download','read','read_only',approval='none',scopes=read_scope),
        _op('drive.files.export','read','read_only',approval='none',scopes=read_scope),
        _op('drive.files.create','consequential','external_side_effect',approval='required',reauth=True,scopes=write_scope,allowed=('public','internal','sensitive'),prohibited=('secret','restricted'),dest=('drive_parent','drive_file'),verify=True),
        _op('drive.files.upload','consequential','external_side_effect',approval='required',reauth=True,scopes=write_scope,allowed=('public','internal','sensitive'),prohibited=('secret','restricted'),dest=('drive_parent','drive_file'),verify=True),
        _op('drive.files.rename','write','external_side_effect',approval='required',reauth=True,scopes=write_scope,allowed=('public','internal','sensitive'),prohibited=('secret','restricted'),dest=('drive_file',),verify=True),
        _op('drive.files.update_content','write','external_side_effect',approval='required',reauth=True,scopes=write_scope,allowed=('public','internal','sensitive'),prohibited=('secret','restricted'),dest=('drive_file',),verify=True),
    )
    return ConnectorManifest('drive','Google Drive','google',1,'oauth2_pkce',read_scope,write_scope,ops,
        token_revocation_supported=True,healthcheck_operation='drive.files.list',configuration_requirements=('google_client_id',),read_only=False,
        scope_reasons=(
            (read_scope[0],'Read metadata and content only for owner-selected Drive files.'),
            (write_scope[0],'Create and update only files created by or explicitly opened/selected for Personal AI; does not grant blanket delete/share/permission control.'),
        ),
        content_limits=(('max_file_bytes',10*1024*1024),('max_pages',10),('max_results',1000),('max_filename_chars',255)),
        supported_content_types=('text/plain','text/csv','application/json','application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/vnd.google-apps.document','application/vnd.google-apps.spreadsheet'))

def sheets_manifest():
    read_scope=('https://www.googleapis.com/auth/spreadsheets.readonly',)
    write_scope=('https://www.googleapis.com/auth/spreadsheets',)
    ops=(
        _op('sheets.spreadsheets.metadata','read','read_only',approval='none',scopes=read_scope),
        _op('sheets.worksheets.list','read','read_only',approval='none',scopes=read_scope),
        _op('sheets.values.read','read','read_only',approval='none',scopes=read_scope),
        _op('sheets.values.batch_read','read','read_only',approval='none',scopes=read_scope),
        _op('sheets.spreadsheets.create','consequential','external_side_effect',approval='required',reauth=True,scopes=write_scope,allowed=('public','internal','sensitive'),prohibited=('secret','restricted'),dest=('spreadsheet',),verify=True),
        _op('sheets.values.update','write','external_side_effect',approval='required',reauth=True,scopes=write_scope,allowed=('public','internal','sensitive'),prohibited=('secret','restricted'),dest=('spreadsheet_range',),verify=True),
        _op('sheets.values.append','consequential','external_side_effect',approval='required',reauth=True,scopes=write_scope,allowed=('public','internal','sensitive'),prohibited=('secret','restricted'),dest=('spreadsheet_range',),verify=True),
    )
    return ConnectorManifest('sheets','Google Sheets','google',1,'oauth2_pkce',read_scope,write_scope,ops,
        token_revocation_supported=True,configuration_requirements=('google_client_id',),read_only=False,
        scope_reasons=(
            (read_scope[0],'Read spreadsheet metadata and explicitly requested ranges.'),
            (write_scope[0],'Create spreadsheets and update/append bounded RAW values. This scope can edit spreadsheets accessible to the connected account; delete, clear, sharing and structural batchUpdate remain prohibited by Personal AI policy.'),
        ),
        content_limits=(('max_worksheets',20),('max_ranges',10),('max_rows',1000),('max_columns',100),('max_cells',50000),('max_write_cells',10000),('max_append_rows',500),('max_request_bytes',1024*1024),('max_response_bytes',2*1024*1024)),
        supported_content_types=('application/vnd.google-apps.spreadsheet','text/csv'))

def slack_manifest():
    return ConnectorManifest('slack','Slack','slack',1,'oauth2_pkce',('channels:history',),('chat:write',),(
        _op('slack.read','read','read_only',approval='none',scopes=('channels:history',),page=True),
        _op('slack.send','consequential','external_side_effect',approval='required',scopes=('chat:write',),dest=('channel',),verify=True),
    ), token_revocation_supported=True, healthcheck_operation='slack.read', configuration_requirements=('slack_client_id',))

def home_assistant_manifest():
    return ConnectorManifest('home_assistant','Home Assistant','home_assistant',1,'bearer_token',operations=(
        _op('home_assistant.read','read','read_only',approval='none'),
        _op('home_assistant.call_service','consequential','external_side_effect',approval='required',dest=('entity','service'),verify=True),
    ), healthcheck_operation='home_assistant.read', configuration_requirements=('home_assistant_url','home_assistant_token'))

def builtin_manifests() -> tuple[ConnectorManifest,...]:
    return (gmail_manifest(),calendar_manifest(),drive_manifest(),sheets_manifest(),slack_manifest(),home_assistant_manifest())
