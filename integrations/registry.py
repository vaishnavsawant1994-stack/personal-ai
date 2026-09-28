from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from integrations.contracts import ConnectorManifest, ConnectorManifestRegistry

@dataclass
class Integration:
    id: str
    name: str
    capabilities: set[str] = field(default_factory=set)
    healthcheck: Callable[[], bool] | None = None
    manifest: ConnectorManifest | None = None
    configured: bool = True

class IntegrationRegistry:
    def __init__(self,*,state_store=None):
        self._items={}; self.manifests=ConnectorManifestRegistry(); self.state_store=state_store; self.gateway=None; self.oauth=None; self.providers={}
    def register_manifest(self,manifest:ConnectorManifest):return self.manifests.register(manifest)
    def register(self,item:Integration):
        if item.id in self._items: raise ValueError(f'duplicate integration: {item.id}')
        if item.manifest is not None:
            try: existing=self.manifests.get(item.manifest.connector_id)
            except KeyError:self.manifests.register(item.manifest)
            if item.manifest.connector_id!=item.id: raise ValueError('integration id must match manifest connector id')
        self._items[item.id]=item
    def get(self,connector_id):return self._items[connector_id]
    def _health(self,x):
        state=self.state_store.health(x.id) if self.state_store else {'state':'disconnected','granted_scopes':[]}
        healthy=None
        if x.configured and x.healthcheck:
            try:
                healthy=bool(x.healthcheck())
                if self.state_store:self.state_store.set_health(x.id,'healthy' if healthy else 'degraded',success=healthy)
            except Exception:
                healthy=False
                if self.state_store:
                    current=self.state_store.health(x.id)
                    if current.get('state') in {'healthy','disconnected','not_configured'}:self.state_store.set_health(x.id,'degraded',error_code='healthcheck_failed',error_message='Connector health check failed')
            state=self.state_store.health(x.id) if self.state_store else state
        elif not x.configured: state={**state,'state':'not_configured'}
        return healthy,state
    def sync_provider_scopes(self,provider,scopes):
        granted=sorted(set(scopes or []))
        for manifest in self.manifests.list():
            if manifest.provider!=provider:continue
            missing=sorted(set(manifest.required_oauth_scopes)-set(granted))
            state='insufficient_scope' if missing else 'healthy'
            if self.state_store:self.state_store.set_health(manifest.connector_id,state,scopes=granted,success=not missing,error_code='insufficient_scope' if missing else None,error_message='Connected account is missing required scopes' if missing else None)
        return granted
    def list(self):
        out=[]
        manifests={m.connector_id:m for m in self.manifests.list()}
        ids=list(dict.fromkeys([*manifests.keys(),*self._items.keys()]))
        for connector_id in ids:
            x=self._items.get(connector_id); manifest=manifests.get(connector_id) or (x.manifest if x else None)
            if x: healthy,state=self._health(x); configured=x.configured; name=x.name; capabilities=sorted(x.capabilities)
            else:
                healthy=None; state=self.state_store.health(connector_id) if self.state_store else {'state':'not_configured','granted_scopes':[]}; state={**state,'state':'not_configured' if state.get('state') in {'disconnected',None} else state.get('state')}; configured=False; name=manifest.display_name if manifest else connector_id; capabilities=[]
            operations=[]
            if manifest and configured and state.get('granted_scopes'):
                missing=set(manifest.required_oauth_scopes)-set(state.get('granted_scopes',[]))
                if missing:state={**state,'state':'insufficient_scope','last_error_message':'Connected account is missing required scopes'}
            if manifest:
                gset=set(state.get('granted_scopes',[]))
                operations=[{'name':o.name,'effect':o.effect,'risk':o.risk,'approval':o.approval,'requires_reauth':o.requires_reauth,'prohibited':o.prohibited,'verification':o.verification_supported,'rollback':o.rollback_available,'required_scopes':list(o.required_scopes),'missing_scopes':sorted(set(o.required_scopes)-gset),'scope_satisfied':not bool(set(o.required_scopes)-gset),'write_enabled':o.effect in {'write','consequential','destructive'} and not o.prohibited and not bool(set(o.required_scopes)-gset)} for o in manifest.operations]
                capabilities=[o.name for o in manifest.operations]
            granted=list(state.get('granted_scopes',[])); required=list(manifest.required_oauth_scopes) if manifest else []; optional=list(manifest.optional_oauth_scopes) if manifest else []; missing=sorted(set(required)-set(granted))
            out.append({'id':connector_id,'name':name,'provider':manifest.provider if manifest else connector_id,'configured':configured,'capabilities':capabilities,'operations':operations,'healthy':healthy,'state':state.get('state'),'granted_scopes':granted,'missing_scopes':missing,'last_success_at':state.get('last_success_at'),'last_checked_at':state.get('last_checked_at'),'last_error':state.get('last_error_message'),'last_error_code':state.get('last_error_code'),'revocation_status':state.get('revocation_status','none'),'auth_type':manifest.authentication_type if manifest else None,'required_scopes':required,'optional_scopes':optional,'scope_reasons':[{'scope':a,'reason':b} for a,b in (manifest.scope_reasons if manifest else ())],'read_only':bool(manifest.read_only) if manifest else False,'content_limits':dict(manifest.content_limits) if manifest else {}})
        return out
