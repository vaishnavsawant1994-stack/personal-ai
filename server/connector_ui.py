from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

JS=r'''(()=>{
const original=window.loadTools;
function badge(v){return `<span>${escapeHtml(String(v||'unknown').replaceAll('_',' '))}</span>`}
function connectorCard(c){const ops=c.operations||[], approvals=[...new Set(ops.map(o=>o.approval))].join(', '), risks=[...new Set(ops.map(o=>o.risk))].join(', '), scopes=c.granted_scopes||[];const canConnect=c.auth_type==='oauth2_pkce'&&c.state!=='healthy';const ro=c.read_only?'read only':'writes individually governed';const missing=c.missing_scopes||[];const canRevoke=['healthy','degraded','rate_limited','authentication_expired','insufficient_scope','revocation_pending'].includes(c.state);const writeOps=ops.filter(o=>['write','consequential','destructive'].includes(o.effect));const writeSummary=writeOps.length?writeOps.map(o=>`${o.name}: ${o.write_enabled?'enabled':'blocked'} · ${o.approval}${o.requires_reauth?' · reauth':''}${o.rollback?' · rollback':' · no auto rollback'}`).join(' | '):'No write capabilities';return `<article class="data-card"><strong>${escapeHtml(c.name||c.id)}</strong><p>${escapeHtml(c.last_error||String(c.state||'not configured').replaceAll('_',' '))}</p><div class="data-meta">${badge(c.state)}${badge(c.provider)}${badge(ro)}${badge(risks||'read only')}${badge('approval '+(approvals||'policy'))}${badge(scopes.length?scopes.length+' scopes':'no scopes')}${badge(missing.length?missing.length+' missing scopes':'scopes ready')}${badge(c.revocation_status&&c.revocation_status!=='none'?'revocation '+c.revocation_status:'')}</div><div class="data-meta"><span>${escapeHtml((c.capabilities||[]).slice(0,12).join(' · ')||'No enabled capabilities')}</span><span>${escapeHtml(writeSummary)}</span>${c.content_limits?`<span>limits ${escapeHtml(JSON.stringify(c.content_limits))}</span>`:''}${c.last_success_at?`<span>last healthy ${escapeHtml(new Date(c.last_success_at*1000).toLocaleString())}</span>`:''}</div><div class="data-actions">${canConnect?`<button data-connector-connect="${escapeHtml(c.id)}">${c.state==='not_configured'?'Configure':'Reconnect'}</button>`:''}${canRevoke?`<button class="danger" data-connector-revoke="${escapeHtml(c.id)}">Revoke</button>`:''}</div></article>`}
window.loadTools=async function(){const [system,data]=await Promise.all([api('/system/status'),api('/connectors')]),tools=system.tools||[],connectors=data.connectors||[];$('moduleBody').innerHTML=`<h2>Approved tools</h2><div class="module-grid">${tools.map(t=>`<article class="data-card"><strong>${escapeHtml(t.name)}</strong><p>${escapeHtml(t.description)}</p><div class="data-meta"><span>${escapeHtml(t.risk)} risk</span></div></article>`).join('')||'<div class="empty-module">No tools are available.</div>'}</div><h2>Apps &amp; Tools connections</h2><p>Connection health, exact granted/missing scopes and per-operation governance. Writes are individually scoped, approval-bound and reauthentication-gated. Delete, share, clear and permission changes remain blocked. Secrets are never shown here.</p><div class="module-grid">${connectors.map(connectorCard).join('')||'<div class="empty-module">No connectors are registered.</div>'}</div>`;document.querySelectorAll('[data-connector-connect]').forEach(b=>b.onclick=async()=>{try{const r=await api('/connectors/'+b.dataset.connectorConnect+'/oauth/start',{method:'POST',body:'{}'});if(r.url){window.location.href=r.url}else showToast('OAuth connection is ready.')}catch(e){showToast(e.message)}});document.querySelectorAll('[data-connector-revoke]').forEach(b=>b.onclick=async()=>{if(!confirm('Revoke this connector on this Personal AI?'))return;try{await api('/connectors/'+b.dataset.connectorRevoke+'/revoke',{method:'POST',body:'{}'});showToast('Connector access revoked.');window.loadTools()}catch(e){showToast(e.message)}})};
})();'''

class ConnectorUiMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        response=await call_next(request)
        if request.url.path not in {'/iphone','/iphone/'} or response.status_code!=200:return response
        ctype=response.headers.get('content-type','')
        if 'text/html' not in ctype:return response
        body=b''
        async for chunk in response.body_iterator:body+=chunk
        text=body.decode('utf-8'); marker='</body>'
        if marker in text:text=text.replace(marker,'<script src="/iphone/connector-ui.js"></script>'+marker,1)
        from starlette.responses import Response
        headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-length','content-encoding'}}
        return Response(text,status_code=response.status_code,headers=headers,media_type='text/html')

def connector_ui_router():
    router=APIRouter()
    @router.get('/iphone/connector-ui.js')
    def connector_js():return Response(JS,media_type='application/javascript')
    return router
