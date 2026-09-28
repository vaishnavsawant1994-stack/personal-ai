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
    return String(run.status || 'unknown').replaceAll('_', ' ');
  };
  const policyText = policy => !policy ? 'Default bounded policy' : `runtime ${policy.max_runtime_seconds}s · steps ${policy.max_steps} · concurrent ${policy.max_concurrent_runs} · model ${policy.max_model_calls} · tools ${policy.max_tool_calls}`;
  const budgetMeta = run => {
    const b=run.budget;if(!b)return '<div class="data-meta"><span>Budget record unavailable</span></div>';
    const c=b.consumption||{},e=b.estimated_usage||{};
    const usage=b.confirmed_usage?'provider usage confirmed':(e.input_tokens?'input tokens estimated':'provider usage unavailable');
    return `<div class="data-meta"><span>steps ${c.completed_steps||0}/${b.policy.max_steps}</span><span>retries ${c.retry_count||0}/${b.policy.max_retries}</span><span>model ${c.model_calls||0}/${b.policy.max_model_calls}</span><span>tools ${c.tool_calls||0}/${b.policy.max_tool_calls}</span><span>${escapeHtml(usage)}</span><span>est. input ${Number(e.input_tokens||0).toLocaleString()}</span><span>confirmed tokens ${Number(c.total_tokens||0).toLocaleString()}</span><span>confirmed cost ${Number(c.confirmed_cost||0).toFixed(4)}</span><span>slot ${b.concurrency_position||'released'}/${b.policy.max_concurrent_runs}</span><span>deadline ${escapeHtml(b.deadline||'none')}</span></div>`;
  };
  const runActions = run => `${run.status==='waiting_approval'?`<button data-run-approve="${run.id}">Approve once</button><button class="danger" data-run-reject="${run.id}">Reject</button>`:''}${run.status==='recovery_required'?`<button data-run-resume="${run.id}">Resume checkpoint</button>`:''}${!['completed','failed','cancelled','budget_exceeded'].includes(run.status)?`<button class="danger" data-run-cancel="${run.id}">Cancel</button>`:''}`;
  const bindWorkflowRunActions = () => {
    document.querySelectorAll('[data-workflow-run]').forEach(button=>button.onclick=async()=>{button.disabled=true;const key=(crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random());try{await api('/workflows/'+button.dataset.workflowRun+'/run',{method:'POST',body:JSON.stringify({context:{surface:'ios-pwa',idempotency_key:key}})});await loadWorkflows()}catch(error){showToast(error.message);button.disabled=false}});
    document.querySelectorAll('[data-run-cancel]').forEach(button=>button.onclick=async()=>{if(confirm('Cancel this workflow run?')){await api('/workflows/runs/'+button.dataset.runCancel+'/cancel',{method:'POST',body:'{}'});loadWorkflows()}});
    document.querySelectorAll('[data-run-resume]').forEach(button=>button.onclick=async()=>{try{await api('/workflows/runs/'+button.dataset.runResume+'/resume',{method:'POST',body:'{}'});loadWorkflows()}catch(error){showToast(error.message)}});
    document.querySelectorAll('[data-run-approve]').forEach(button=>button.onclick=async()=>{try{await api('/workflows/runs/'+button.dataset.runApprove+'/approve',{method:'POST',body:'{}'});loadWorkflows()}catch(error){showToast(error.message)}});
    document.querySelectorAll('[data-run-reject]').forEach(button=>button.onclick=async()=>{await api('/workflows/runs/'+button.dataset.runReject+'/reject',{method:'POST',body:'{}'});loadWorkflows()});
  };
  loadWorkflows = async function(){
    const data=await api('/workflows'),workflows=data.workflows||[],runs=data.runs||[];
    $('moduleBody').innerHTML=`<div class="module-toolbar"><button id="workflowAdd">＋ New workflow</button><button id="workflowRefresh">Refresh</button><span>${runs.length} runs</span></div><h2>Workflows</h2><div class="module-grid">${workflows.map(workflow=>`<article class="data-card"><strong>${escapeHtml(workflow.title)}</strong><p>${(workflow.steps||[]).length} persisted steps · ${workflow.enabled&&!workflow.paused?'Ready':'Paused'}</p><div class="data-meta"><span>${escapeHtml(policyText(workflow.policy))}</span><span>approval ${escapeHtml((workflow.policy||{}).approval_threshold||'consequential')}</span></div><div class="data-actions"><button data-workflow-run="${workflow.id}">Run</button></div></article>`).join('')||'<div class="empty-module">Create a governed workflow for repeatable work.</div>'}</div><h2>Runs, approvals &amp; budgets</h2><div class="module-grid">${runs.map(run=>`<article class="data-card"><strong>${escapeHtml(stateLabel(run))} · step ${escapeHtml(run.current_step_step||run.current_step)}</strong><p>${escapeHtml((run.budget&&run.budget.stop_reason)||run.error||run.id)}</p>${budgetMeta(run)}<div class="data-actions">${runActions(run)}</div></article>`).join('')||'<div class="empty-module">No workflow runs.</div>'}</div>`;
    $('workflowRefresh').onclick=loadWorkflows;
    $('workflowAdd').onclick=async()=>{const title=prompt('Workflow name');if(!title)return;const instruction=prompt('What should this workflow do?');if(!instruction)return;await api('/workflows',{method:'POST',body:JSON.stringify({title,trigger:{type:'manual'},steps:[{kind:'prompt',prompt:instruction}]})});loadWorkflows()};
    bindWorkflowRunActions();
  };
  loadActivityFeed = async function(){
    const [activityData,workflowData]=await Promise.all([api('/activities?limit=200'),api('/workflows')]);
    const activities=activityData.activities||[],runs=workflowData.runs||[];
    $('moduleBody').innerHTML=`<div class="module-toolbar"><button id="activityRefresh">Refresh</button><span>${activities.length} recent audited events</span><span>${runs.filter(r=>!['completed','failed','cancelled','budget_exceeded'].includes(r.status)).length} active workflows</span></div><h2>Workflow budget activity</h2><div class="module-grid">${runs.slice(0,12).map(run=>`<article class="data-card"><strong>${escapeHtml(stateLabel(run))}</strong><p>${escapeHtml((run.budget&&run.budget.stop_reason)||run.error||run.id)}</p>${budgetMeta(run)}</article>`).join('')||'<div class="empty-module">No workflow runs.</div>'}</div><h2>Audited activity</h2><div class="module-grid">${activities.map(item=>`<article class="data-card"><strong>${escapeHtml(item.category)} · ${escapeHtml(item.action)}</strong><p>${escapeHtml(new Date(item.created_at).toLocaleString())}</p><div class="data-meta"><span>${escapeHtml(JSON.stringify(item.payload).slice(0,180))}</span></div></article>`).join('')||'<div class="empty-module">No audited activity yet.</div>'}</div>`;
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
