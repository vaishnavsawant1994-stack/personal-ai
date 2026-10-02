from __future__ import annotations
from contextlib import asynccontextmanager
import asyncio
import json
from app.main import build_runtime
from core.config import settings
from core.storage import validate_runtime_storage
from security.pwa_sessions import PwaSessionStore
from server.api import create_app
from server.activities_api import activities_router
from server.apps_tools_api import apps_tools_router
from server.devices_presence_api import devices_presence_router
from server.approval_api import approval_router
from server.approvals_center_api import approvals_center_router
from server.automation_visibility_api import automation_visibility_router
from server.recovery_visibility_api import recovery_visibility_router
from server.cloud_security import cloud_security_router
from server import iphone_pwa as iphone_pwa_module
from server.owner_product import owner_product_router
from server.capability_console import capability_console_router
from server.memory_knowledge_inspection import memory_knowledge_inspection_router
from server.memory_governance_api import memory_governance_router
from server.everyday_intelligence_api import everyday_intelligence_router
from server.personal_operations_api import personal_operations_router
from server.multimodal_world_api import multimodal_world_router
from server.continuity_sync_api import continuity_sync_router
from server.pwa_security import pwa_security_router
from server.pwa_session_middleware import PwaSessionMiddleware
from server.logical_request_middleware import LogicalRequestMiddleware
from server.request_aware_pwa_state import RequestAwareIphonePwaState
from server.runtime_state_api import runtime_state_router
from server.session_bound_executor import SessionBoundExecutor
from server.conversation_voice_api import conversation_voice_router
from server.workflow_budget_api import workflow_budget_router
from server.workflow_budget_ui import WorkflowBudgetUiMiddleware, workflow_budget_ui_router
from server.connector_api import connector_router
from server.connector_ui import ConnectorUiMiddleware, connector_ui_router
from server.connector_oauth_callback import connector_oauth_callback_router

class CanonicalConversationProjection:
    """Compatibility view for legacy PWA conversation helpers."""
    def __init__(self,continuity):self._continuity=continuity
    def __getattr__(self,name):return getattr(self._continuity,name)
    def append(self,thread_id,*,device_id,kind,payload,event_id=None):
        if kind in {'user_message','assistant_message'} and event_id is None:
            return {'event_id':None,'sequence':None,'thread_id':thread_id,'duplicate':True,'projection':'canonical-turn-runtime'}
        return self._continuity.append(thread_id,device_id=device_id,kind=kind,payload=payload,event_id=event_id)

storage_status=validate_runtime_storage(settings)
runtime=build_runtime();runtime['storage_status']=storage_status;runtime['pwa_sessions']=PwaSessionStore(settings.data_dir/'pwa-sessions.sqlite3')
print(json.dumps({'event':'storage.ready',**storage_status}),flush=True)

@asynccontextmanager
async def lifespan(app):
    runtime['automations'].start();evaluation_task=None
    if settings.model_evaluation_on_startup:
        async def evaluate_model():
            result=await asyncio.to_thread(runtime['model_evaluation'].run);safe={key:value for key,value in result.items() if key!='cases'};safe['case_results']=[{'case':item['case'],'passed':item['passed'],'error_code':item['error_code']} for item in result['cases']];print(json.dumps({'event':'model.dialogue_evaluation',**safe}),flush=True)
        evaluation_task=asyncio.create_task(evaluate_model())
    try:yield
    finally:
        if evaluation_task and not evaluation_task.done():evaluation_task.cancel()
        runtime['voice'].stop();runtime['automations'].stop();runtime['telemetry'].persist();runtime['apns'].close()

app=create_app(runtime['executor'],settings,device_registry=runtime['device_registry'],device_gateway=runtime['device_gateway'],second_brain=runtime['second_brain'],automations=runtime['automations'],runtime=runtime)
app.add_middleware(LogicalRequestMiddleware)
app.add_middleware(PwaSessionMiddleware,sessions=runtime['pwa_sessions'],device_registry=runtime['device_registry'],cookie_max_age=60*60*24*max(1,min(int(getattr(settings,'iphone_device_cookie_days',365)),3650)))
app.add_middleware(WorkflowBudgetUiMiddleware);app.add_middleware(ConnectorUiMiddleware)
pwa_runtime=dict(runtime);pwa_runtime['executor']=SessionBoundExecutor(runtime['executor'],continuity=runtime['continuity'],surface='iphone-pwa');pwa_runtime['continuity']=CanonicalConversationProjection(runtime['continuity'])
# Stage 2 durable ApprovalManager remains the sole approval authority.
app.include_router(approval_router(runtime,pwa_runtime['executor']))
app.include_router(approvals_center_router(runtime))
# Stage 3 canonical conversation/voice transport remains authoritative.
app.include_router(conversation_voice_router(runtime,pwa_runtime['executor']))
_original_pwa_state=iphone_pwa_module.IphonePwaState
iphone_pwa_module.IphonePwaState=lambda:RequestAwareIphonePwaState(cancel_turn=pwa_runtime['executor'].cancel_turn)
try:app.include_router(iphone_pwa_module.iphone_pwa_router(pwa_runtime,settings,include_legacy_runtime_routes=False))
finally:iphone_pwa_module.IphonePwaState=_original_pwa_state
app.include_router(pwa_security_router(runtime));app.include_router(cloud_security_router(runtime));app.include_router(activities_router(runtime));app.include_router(apps_tools_router(runtime));app.include_router(devices_presence_router(runtime));app.include_router(automation_visibility_router(runtime));app.include_router(recovery_visibility_router(runtime));app.include_router(runtime_state_router(runtime));app.include_router(memory_knowledge_inspection_router(runtime));app.include_router(memory_governance_router(runtime));app.include_router(everyday_intelligence_router(runtime));app.include_router(personal_operations_router(runtime));app.include_router(multimodal_world_router(runtime));app.include_router(continuity_sync_router(runtime));app.include_router(owner_product_router(runtime));app.include_router(workflow_budget_router(runtime));app.include_router(workflow_budget_ui_router());app.include_router(connector_router(runtime));app.include_router(connector_oauth_callback_router());app.include_router(connector_ui_router());app.include_router(capability_console_router(runtime));app.router.lifespan_context=lifespan