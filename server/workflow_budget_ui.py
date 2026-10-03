from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

WORKFLOW_BUDGET_UI = r'''(() => {
  const stateLabel = run => {
    const reason = String((run.budget && run.budget.stop_reason) || run.error || '');
    if (reason.includes('Maximum runtime')) return 'Maximum runtime reached';
    if (reason.includes('Concurrent run')) return 'Concurrent run limit reached';
    if (reason.includes('Model-call')) return 'Model-call limit reached';
    if (reason.includes('Tool-call')) return 'Tool-call limit reached';
    if (reason.includes('Token/cost')) return 'Token/cost budget unavailable';
    if (reason.includes('Emergency Stop')) return 'Emergency Stop active';
    if (run.status === 'waiting_approval') return 'Waiting for approval';
    if (run.status === 'recovery_required') return 'Recovery review required';
    if (run.status === 'cancelled') return 'Cancelled by owner';
    if (run.status === 'budget_exceeded') return reason || 'Workflow limit reached';
    const labels={queued:'Queued',running:'Running',rolling_back:'Rolling back',waiting_approval:'Awaiting approval',recovery_required:'Recovery required',interrupted:'Interrupted',completed:'Completed',failed:'Failed',cancelled:'Cancelled',budget_exceeded:'Budget exceeded'};
    return labels[String(run.status||'')] || 'Unknown state';
  };
  const policyText = policy => !policy ? 'Default bounded policy' : `runtime ${policy.max_runtime_seconds}s · steps ${policy.max_steps} · concurrent ${policy.max_concurrent_runs} · model ${policy.max_model_calls} · tools ${policy.max_tool_calls}`;
  const budgetMeta = run => {
    const b=run.budget;if(!b)return '<div class="data-meta"><span>Budget record unavailable</span></div>';
    const c=b.consumption||{},e=b.estimated_usage||{};
    const usage=b.confirmed_usage?'provider usage confirmed':(e.input_tokens?'input tokens estimated':'provider usage unavailable');
    return `<div class="data-meta"><span>steps ${c.completed_steps||0}/${b.policy.max_steps}</span><span>retries ${c.retry_count||0}/${b.policy.max_retries}</span><span>model ${c.model_calls||0}/${b.policy.max_model_calls}</span><span>tools ${c.tool_calls||0}/${b.policy.max_tool_calls}</span><span>${escapeHtml(usage)}</span><span>est. input ${Number(e.input_tokens||0).toLocaleString()}</span><span>confirmed tokens ${Number(c.total_tokens||0).toLocaleString()}</span><span>confirmed cost ${Number(c.confirmed_cost||0).toFixed(4)}</span><span>slot ${b.concurrency_position||'released'}/${b.policy.max_concurrent_runs}</span><span>deadline ${escapeHtml(b.deadline||'none')}</span></div>`;
  };
  const runActions = run => `${run.status==='waiting_approval'?`<button data-run-approve="${run.id}">Approve once</button><button class="danger" data-run-reject="${run.id}">Reject</button>`:''}${['recovery_required','interrupted'].includes(run.status)?`<button data-run-resume="${run.id}">Resume checkpoint</button>`:''}${!['completed','failed','cancelled','budget_exceeded','interrupted'].includes(run.status)?`<button class="danger" data-run-cancel="${run.id}">Cancel</button>`:''}`;
  const bindWorkflowRunActions = () => {
    document.querySelectorAll('[data-workflow-run]').forEach(button=>button.onclick=async()=>{button.disabled=true;const key=(crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random());try{await api('/workflows/'+button.dataset.workflowRun+'/run',{method:'POST',body:JSON.stringify({context:{surface:'ios-pwa',idempotency_key:key}})});await loadWorkflows()}catch(error){showToast(error.message);button.disabled=false}});
    document.querySelectorAll('[data-run-cancel]').forEach(button=>button.onclick=async()=>{if(await requestConfirmation('Cancel this workflow run?')){try{await api('/workflows/runs/'+button.dataset.runCancel+'/cancel',{method:'POST',body:'{}'});loadWorkflows()}catch(error){showToast(error.message||'Could not cancel workflow run.')}}});
    document.querySelectorAll('[data-run-resume]').forEach(button=>button.onclick=async()=>{try{await api('/workflows/runs/'+button.dataset.runResume+'/resume',{method:'POST',body:'{}'});loadWorkflows()}catch(error){showToast(error.message)}});
    document.querySelectorAll('[data-run-approve]').forEach(button=>button.onclick=async()=>{try{await api('/workflows/runs/'+button.dataset.runApprove+'/approve',{method:'POST',body:'{}'});loadWorkflows()}catch(error){showToast(error.message)}});
    document.querySelectorAll('[data-run-reject]').forEach(button=>button.onclick=async()=>{await api('/workflows/runs/'+button.dataset.runReject+'/reject',{method:'POST',body:'{}'});loadWorkflows()});
  };
  let workflowFilter='all',workflowQuery='';
  const activeStatuses=['queued','running','rolling_back','waiting_approval','recovery_required','interrupted','paused','scheduled','retrying'];
  const activeRun=run=>activeStatuses.includes(String(run.status||'').toLowerCase());
  const workflowSafeText=value=>escapeHtml(String(value??''));
  const workflowStatusClass=run=>run.status==='completed'?'completed':['waiting_approval','recovery_required'].includes(run.status)?'pending':['failed','budget_exceeded'].includes(run.status)?'danger':['cancelled','interrupted'].includes(run.status)?'neutral':['running','rolling_back'].includes(run.status)?'running':'neutral';
  const workflowStatusLabel=run=>stateLabel(run);
  const workflowWhen=run=>{const value=run.updated_at||run.started_at||run.created_at;if(!value)return 'Time unavailable';const date=new Date(value);return Number.isNaN(date.getTime())?'Time unavailable':`${Math.max(0,Math.floor((Date.now()-date.getTime())/60000))<60?`${Math.max(0,Math.floor((Date.now()-date.getTime())/60000))} min ago`:Math.max(0,Math.floor((Date.now()-date.getTime())/3600000))<24?`${Math.max(1,Math.floor((Date.now()-date.getTime())/3600000))} hr ago`:date.toLocaleDateString()}`};
  const workflowIcon=name=>`<span class="workflow-row-icon">${sectionIcon(name==='face'?'activity':name==='check'?'check':'workflow')}</span>`;
  function workflowRunCard(run){const title=run.workflow_title||run.title||`Workflow run ${String(run.id||'').slice(0,8)}`,description=run.status==='waiting_approval'?'Waiting for owner approval.':run.status==='recovery_required'?'A persisted checkpoint needs recovery review.':run.error||run.budget?.stop_reason||`Step ${run.current_step_step||run.current_step||0}`;return `<article class="workflow-card workflow-run-card">${workflowIcon(run.status==='waiting_approval'?'face':run.status==='completed'?'check':'workflow')}<span class="workflow-card-copy"><strong>${workflowSafeText(title)}</strong><small>${workflowSafeText(description)}</small><span class="workflow-chip-row"><span class="workflow-chip">Workflow run</span><span class="workflow-chip ${workflowStatusClass(run)}">${workflowSafeText(workflowStatusLabel(run))}</span></span></span><time>${workflowSafeText(workflowWhen(run))}</time><span class="workflow-card-actions">${runActions(run)}</span></article>`}
  function workflowDefinitionCard(workflow){const state=workflow.enabled&&!workflow.paused?'Enabled':'Paused';return `<article class="workflow-card">${workflowIcon('workflow')}<span class="workflow-card-copy"><strong>${workflowSafeText(workflow.title||'Untitled workflow')}</strong><small>${workflowSafeText(workflow.description||`${(workflow.steps||[]).length} persisted steps · ${state}`)}</small><span class="workflow-chip-row"><span class="workflow-chip">${workflowSafeText(state)}</span><span class="workflow-chip">${workflowSafeText((workflow.policy||{}).approval_threshold||'Governed')}</span></span></span><span class="workflow-card-actions"><button type="button" data-workflow-run="${workflowSafeText(workflow.id)}" aria-label="Run ${workflowSafeText(workflow.title)}">Run</button></span></article>`}
  loadWorkflows = async function(){
    const focus=document.activeElement?.id==='workflowSearch'?{start:document.activeElement.selectionStart,end:document.activeElement.selectionEnd}:null;
    const body=$('moduleBody');body.innerHTML=`<div class="section-page workflow-page">${sectionHeader('Workflows','Governed, resumable work with checkpoints, approvals and cancellation.')}<div class="section-search-skeleton"></div><div class="activity-stat-grid workflow-stat-grid"><i></i><i></i><i></i></div><div class="apps-loading-row"></div><div class="apps-loading-row"></div></div>`;
    let data;try{data=await api('/workflows')}catch(error){body.innerHTML=`<div class="section-page workflow-page">${sectionHeader('Workflows','Governed, resumable work with checkpoints, approvals and cancellation.')}<section class="section-empty" role="alert"><strong>${error.status===403?'This device is not permitted to manage workflows.':error.status===401?'Sign in again to manage workflows.':'Unable to load workflows.'}</strong><button id="workflowRetry" class="ui-button" type="button">Retry</button></section></div>`;bindSectionHeader();$('workflowRetry').onclick=()=>loadWorkflows();return}const workflows=Array.isArray(data.workflows)?data.workflows:[],runs=Array.isArray(data.runs)?data.runs:[],active=runs.filter(activeRun),waiting=runs.filter(run=>run.status==='waiting_approval');
    const q=workflowQuery.trim().toLowerCase(),filterRecords=rows=>rows.filter(row=>{const value=`${row.title||''} ${row.workflow_title||''} ${row.description||''} ${row.status||''} ${row.error||''}`.toLowerCase();if(q&&!value.includes(q))return false;if(workflowFilter==='active')return row.id&&active.includes(row);if(workflowFilter==='approvals')return row.status==='waiting_approval';if(workflowFilter==='templates')return row.is_template===true||row.template===true;if(workflowFilter==='completed')return row.status==='completed';return true});
    const selectedRuns=filterRecords(runs),selectedWorkflows=workflowFilter==='active'||workflowFilter==='approvals'||workflowFilter==='completed'?[]:filterRecords(workflows),showActive=workflowFilter==='all'||workflowFilter==='active'||workflowFilter==='approvals',showDefinitions=workflowFilter==='all'||workflowFilter==='templates',showHistory=workflowFilter==='all'||workflowFilter==='completed'||workflowFilter==='approvals';
    body.innerHTML=`<div class="section-page workflow-page">${sectionHeader('Workflows','Governed, resumable work with checkpoints, approvals and cancellation.')}${sectionSearchMarkup('workflowSearch','Search workflows or runs…',workflowQuery)}<div class="section-filter-row" role="group" aria-label="Filter workflows">${[['all','All'],['active','Active'],['approvals','Approvals'],['templates','Templates'],['completed','Completed']].map(([key,label])=>`<button type="button" class="section-filter${workflowFilter===key?' active':''}" data-workflow-filter="${key}" aria-pressed="${workflowFilter===key}">${label}</button>`).join('')}</div><div class="activity-stat-grid workflow-stat-grid"><article><span class="section-action-icon">${sectionIcon('workflow')}</span><strong>${workflows.length+runs.length}</strong><small>Total</small></article><article><span class="section-action-icon completed">${sectionIcon('workflow')}</span><strong>${runs.filter(run=>run.status==='running'||run.status==='rolling_back'||run.status==='queued').length}</strong><small>Running</small></article><article><span class="section-action-icon pending">${sectionIcon('activity')}</span><strong>${waiting.length}</strong><small>Waiting approval</small></article></div><div class="workflow-toolbar"><button id="workflowAdd" class="workflow-primary">${sectionIcon('plus')} New workflow</button><button id="workflowRefresh" class="workflow-refresh">${sectionIcon('refresh')} Refresh</button><span>${runs.length} ${runs.length===1?'run':'runs'}</span></div>${showActive?`<section class="section-list-area"><div class="section-group-heading"><h2>Active runs</h2><button class="section-see-all" type="button" data-workflow-filter="active">See all ›</button></div>${selectedRuns.filter(activeRun).map(workflowRunCard).join('')||'<div class="section-empty"><strong>No active runs.</strong><span>Nothing is currently running or awaiting action.</span></div>'}</section>`:''}${showDefinitions?`<section class="section-list-area"><div class="section-group-heading"><h2>Your workflows</h2><button class="section-see-all" type="button" data-workflow-filter="all">See all ›</button></div>${selectedWorkflows.map(workflowDefinitionCard).join('')||'<div class="section-empty"><strong>No workflows yet.</strong><span>Create a governed workflow for repeatable work.</span></div>'}</section>`:''}${showHistory?`<section class="section-list-area"><div class="section-group-heading"><h2>Runs, approvals &amp; budgets</h2><button class="section-see-all" type="button" data-workflow-filter="completed">See all ›</button></div>${selectedRuns.slice(0,30).map(workflowRunCard).join('')||'<div class="section-empty"><strong>No workflow runs match this view.</strong></div>'}</section>`:''}<button id="workflowCustom" class="workflow-custom">${sectionIcon('plus')}<span>Create custom workflow</span>${sectionIcon('next')}</button></div>`;
    document.body.classList.add('focused-module');$('modulePanel').dataset.surface='workflows';
    bindSectionHeader();
    $('workflowSearch').oninput=()=>{workflowQuery=$('workflowSearch').value;loadWorkflows()};if(focus){$('workflowSearch').focus({preventScroll:true});$('workflowSearch').setSelectionRange(focus.start,focus.end)}
    document.querySelectorAll('[data-workflow-filter]').forEach(button=>button.onclick=()=>{workflowFilter=button.dataset.workflowFilter;loadWorkflows()});$('workflowRefresh').onclick=()=>loadWorkflows();
    const create=async()=>{const title=await requestText('Workflow name');if(!title?.trim())return;const instruction=await requestText('What should this workflow do?');if(!instruction?.trim())return;try{await api('/workflows',{method:'POST',body:JSON.stringify({title:title.trim(),trigger:{type:'manual'},steps:[{kind:'prompt',prompt:instruction.trim()}]})});showToast('Workflow created.');await loadWorkflows()}catch(error){showToast(error.message||'Could not create workflow.')}};$('workflowAdd').onclick=create;$('workflowCustom').onclick=create;
    bindWorkflowRunActions();
  };
  loadActivityFeed = async function(){
    const [activityResult,workflowResult]=await Promise.allSettled([api('/activities?limit=200'),api('/workflows')]);
    const activityData=activityResult.status==='fulfilled'?activityResult.value:{},workflowData=workflowResult.status==='fulfilled'?workflowResult.value:{},activities=activityData.activities||[],runs=workflowData.runs||[],failures=[activityResult,workflowResult].filter(result=>result.status==='rejected');
    $('moduleBody').innerHTML=`${failures.length?`<div class="module-notice" role="status">${failures.map(result=>result.reason?.status===403?'Some activity requires additional permission.':'Some activity data could not be loaded.').join(' ')}</div>`:''}<div class="module-toolbar"><button id="activityRefresh" type="button">Refresh</button><span>${activities.length} recent audited events</span><span>${runs.filter(r=>!['completed','failed','cancelled','budget_exceeded'].includes(r.status)).length} active workflows</span></div><h2>Workflow budget activity</h2><div class="module-grid">${runs.slice(0,12).map(run=>`<article class="data-card"><strong>${escapeHtml(stateLabel(run))}</strong><p>${escapeHtml((run.budget&&run.budget.stop_reason)||run.error||run.id)}</p>${budgetMeta(run)}</article>`).join('')||'<div class="empty-module">No workflow runs.</div>'}</div><h2>Audited activity</h2><div class="module-grid">${activities.map(item=>{const payload=item.payload&&typeof item.payload==='object'?JSON.stringify(item.payload):String(item.payload||'');return`<article class="data-card"><strong>${escapeHtml(item.category||'Activity')} · ${escapeHtml(item.action||'updated')}</strong><p>${escapeHtml(item.created_at?new Date(item.created_at).toLocaleString():'Time unavailable')}</p>${payload?`<div class="data-meta"><span>${escapeHtml(payload.slice(0,180))}</span></div>`:''}</article>`}).join('')||'<div class="empty-module">No audited activity yet.</div>'}</div>`;
    $('activityRefresh').onclick=loadActivityFeed;
  };
})();'''


def workflow_budget_ui_router():
    router = APIRouter(prefix='/iphone', tags=['workflow-budget-ui'])
    @router.get('/workflow-budget-ui.js', include_in_schema=False)
    def script():
        return Response(WORKFLOW_BUDGET_UI, media_type='application/javascript', headers={'Cache-Control': 'no-store'})
    return router


class WorkflowBudgetUiMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path not in {'/iphone','/iphone/'} or 'text/html' not in response.headers.get('content-type',''):
            return response
        body=b''.join([chunk async for chunk in response.body_iterator]); text=body.decode('utf-8')
        if '</body>' not in text or '/iphone/workflow-budget-ui.js' in text:
            return Response(content=body,status_code=response.status_code,headers=dict(response.headers),media_type='text/html')
        text=text.replace('</body>','<script src="/iphone/workflow-budget-ui.js"></script>\n</body>',1)
        headers={k:v for k,v in response.headers.items() if k.lower()!='content-length'}
        return Response(content=text,status_code=response.status_code,headers=headers,media_type='text/html')
