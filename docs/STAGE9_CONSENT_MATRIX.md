# Stage 9 consent matrix

Generated from `docs/stage9_route_classification.json`. This is not a Stage 9 freeze.
A row records the handler check that was found. `not-in-handler` means this function does not itself read Emergency Stop.

## Former Stage 9 gaps

These three routes were gaps at the Stage 9 freeze `ddd53d1`. They were closed after the Stage 9 freeze. The freeze SHA was not moved.

| Route | Closure |
| --- | --- |
| GET /workflows | A device with `workflow:read` sees only workflows it created. Another device gets an empty list, not the steps. |
| GET /capabilities/api/status | Requires a trusted device with `device:read`. Presence only. No Memory or Knowledge body. |
| POST /iphone/api/logout | Requires the device cookie, revokes that device and its server sessions, then clears the cookies. Another device stays active. |

## Consequential routes

| Method | Route | Scope | Binding | E-stop | Approval | Durable writes | File |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GET | /dashboard/status | device:read | bearer | not-in-handler | none-visible | none-visible | dashboard/api.py |
| GET | /dashboard/devices | device:read | bearer | not-in-handler | none-visible | none-visible | dashboard/api.py |
| GET | /dashboard/automations | workflow:read | bearer | not-in-handler | none-visible | none-visible | dashboard/api.py |
| GET | /dashboard/memory | memory:sensitive | bearer | not-in-handler | none-visible | none-visible | dashboard/api.py |
| POST | /dashboard/tool | ai:chat | bearer | not-in-handler | none-visible | none-visible | dashboard/api.py |
| POST | /dashboard/device/{device_id}/command | device:read | bearer | not-in-handler | none-visible | none-visible | dashboard/api.py |
| GET | /iphone/api/activities/{activity_id} | activities:read | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/activities_api.py |
| POST | /pair/start | loopback | loopback | not-in-handler | none-visible | create | server/api.py |
| POST | /pair/confirm | enrollment | one-time-pairing-code | not-in-handler | none-visible | none-visible | server/api.py |
| GET | /oauth/start/{provider_id} | loopback | loopback | not-in-handler | none-visible | none-visible | server/api.py |
| GET | /oauth/callback | loopback | loopback | not-in-handler | none-visible | none-visible | server/api.py |
| POST | /command | ai:chat | bearer | delegated-to-executor-or-relay | none-visible | none-visible | server/api.py |
| POST | /continuity/resume | ai:chat | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| GET | /continuity/sync | ai:chat | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| POST | /continuity/append | ai:chat | bearer | not-in-handler | none-visible | append | server/api.py |
| POST | /continuity/context | ai:chat | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| POST | /continuity/handoff | ai:chat | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| POST | /proactive/consider | ai:chat | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| GET | /proactive/history | ai:chat | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| GET | /workflows | workflow:read | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| GET | /workflows/runs | workflow:read | bearer | not-in-handler | none-visible | append | server/api.py |
| POST | /workflows/create | workflow:write | bearer | not-in-handler | none-visible | create_workflow | server/api.py |
| POST | /workflows/run | workflow:write | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| POST | /workflows/pause | workflow:write | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| POST | /workflows/approval | workflow:approve | bearer | not-in-handler | mentions-approval | approve_run, reject_run | server/api.py |
| GET | /benchmark | qualification:read | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| POST | /benchmark/run | qualification:record | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| POST | /cloud/session | cloud-session | owner-or-cloud-session | not-in-handler | none-visible | none-visible | server/api.py |
| POST | /cloud/session/revoke | status:read | bearer | not-in-handler | none-visible | revoke_session | server/api.py |
| POST | /cloud/command | ai:chat | bearer | delegated-to-executor-or-relay | none-visible | none-visible | server/api.py |
| POST | /cloud/memory/search | memory:read | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| GET | /cloud/status | status:read | bearer | not-in-handler | none-visible | none-visible | server/api.py |
| GET | /cloud/events | status:read | bearer | not-in-handler | mentions-approval | none-visible | server/api.py |
| GET | /cloud/activities | status:read | bearer | not-in-handler | mentions-approval | append, audit_entries | server/api.py |
| GET | /cloud/approval/{approval_id} | approval:read | bearer | not-in-handler | mentions-approval | none-visible | server/api.py |
| POST | /cloud/approval | approval:write | bearer | not-in-handler | mentions-approval | none-visible | server/api.py |
| POST | /cloud/emergency-stop | cloud-session | owner-or-cloud-session | checked-in-handler | none-visible | set_emergency_stop | server/api.py |
| WEBSOCKET | /device/ws/{device_id} | ai:chat | bearer | not-in-handler | none-visible | append | server/api.py |
| GET | /dashboard-ui | loopback | loopback | not-in-handler | none-visible | none-visible | server/api.py |
| GET | /iphone/api/approvals | ai:chat | trusted-session-or-device | not-in-handler | mentions-approval | none-visible | server/approval_api.py |
| POST | /iphone/api/approval/{approval_id}/approve | ai:chat | trusted-session-or-device | not-in-handler | fresh-reauth | approve | server/approval_api.py |
| POST | /iphone/api/approval/{approval_id}/reject | ai:chat | trusted-session-or-device | not-in-handler | mentions-approval | reject | server/approval_api.py |
| GET | /iphone/api/approvals-center/{approval_id} | ai:chat | trusted-session-or-device | not-in-handler | mentions-approval | none-visible | server/approvals_center_api.py |
| GET | /iphone/api/apps-tools/tools | device:read | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/apps_tools_api.py |
| GET | /iphone/api/apps-tools/tools/{tool_id} | device:read | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/apps_tools_api.py |
| GET | /iphone/api/apps-tools/apps | device:read | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/apps_tools_api.py |
| GET | /iphone/api/apps-tools/apps/{app_id} | device:read | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/apps_tools_api.py |
| GET | /iphone/api/automation-visibility/automations | workflow:read | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/automation_visibility_api.py |
| GET | /iphone/api/automation-visibility/workflows | workflow:read | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/automation_visibility_api.py |
| GET | /iphone/api/automation-visibility/runs | workflow:read | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/automation_visibility_api.py |
| GET | /capabilities/api/status | none | none | not-in-handler | none-visible | none-visible | server/capability_console.py |
| POST | /cloud/reauth | status:read | bearer | not-in-handler | fresh-reauth | none-visible | server/cloud_security.py |
| GET | /iphone/api/connectors/{connector_id} | device:read | device-cookie | not-in-handler | none-visible | none-visible | server/connector_api.py |
| POST | /iphone/api/connectors/{connector_id}/oauth/start | device:admin | device-cookie | not-in-handler | mentions-approval | none-visible | server/connector_api.py |
| POST | /iphone/api/connectors/{connector_id}/oauth/complete | device:admin | device-cookie | not-in-handler | none-visible | none-visible | server/connector_api.py |
| POST | /iphone/api/connectors/oauth/finalize | device:admin | device-cookie | not-in-handler | mentions-approval | none-visible | server/connector_api.py |
| POST | /iphone/api/connectors/{connector_id}/revoke | device:admin | device-cookie | not-in-handler | none-visible | none-visible | server/connector_api.py |
| POST | /iphone/api/connectors/drive/files/{file_id}/knowledge | knowledge:write | device-cookie | not-in-handler | mentions-approval | none-visible | server/connector_knowledge_api.py |
| POST | /iphone/api/connectors/sheets/{spreadsheet_id}/knowledge | knowledge:write | device-cookie | not-in-handler | mentions-approval | none-visible | server/connector_knowledge_api.py |
| GET | /iphone/api/continuity/status | trusted-session | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/continuity_sync_api.py |
| POST | /iphone/api/continuity/reconcile | trusted-session | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/continuity_sync_api.py |
| POST | /iphone/api/continuity/handoff | trusted-session | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/continuity_sync_api.py |
| GET | /iphone/api/continuity/operations/{operation_id} | trusted-session | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/continuity_sync_api.py |
| GET | /iphone/api/continuity/world/{observation_id} | trusted-session | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/continuity_sync_api.py |
| POST | /iphone/api/voice/turn | ai:chat | trusted-session-or-device | not-in-handler | mentions-approval | none-visible | server/conversation_voice_api.py |
| POST | /iphone/api/voice/barge | ai:chat | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/conversation_voice_api.py |
| POST | /iphone/api/voice/operation/cancel | ai:chat | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/conversation_voice_api.py |
| POST | /iphone/api/voice/client-event | ai:chat | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/conversation_voice_api.py |
| GET | /iphone/api/conversations | ai:chat | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/conversation_voice_api.py |
| GET | /iphone/api/conversations/{conversation_id} | ai:chat | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/conversation_voice_api.py |
| GET | /iphone/api/devices-presence/{device_id} | device:read | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/devices_presence_api.py |
| DELETE | /iphone/api/devices-presence/{device_id} | device:admin | trusted-session-or-device | not-in-handler | fresh-reauth | audit, revoke, revoke_device | server/devices_presence_api.py |
| GET | /iphone/api/everyday/active | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/everyday_intelligence_api.py |
| GET | /iphone/api/everyday/due | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/everyday_intelligence_api.py |
| GET | /iphone/api/everyday/briefing | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/everyday_intelligence_api.py |
| GET | /iphone/api/everyday/{item_id}/history | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/everyday_intelligence_api.py |
| GET | /iphone/api/everyday/{item_id}/context | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/everyday_intelligence_api.py |
| POST | /iphone/api/everyday/{item_id}/complete | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/everyday_intelligence_api.py |
| POST | /iphone/api/everyday/{item_id}/snooze | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/everyday_intelligence_api.py |
| POST | /iphone/api/everyday/{item_id}/reschedule | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/everyday_intelligence_api.py |
| POST | /iphone/api/everyday/{item_id}/cancel | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/everyday_intelligence_api.py |
| GET | /iphone/api/status | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| GET | /iphone/api/access/security | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/access/google/login | transport | none | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/access/password/setup | ai:chat | device-cookie | not-in-handler | fresh-reauth | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/access/password/login | transport | none | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/access/recovery/regenerate | ai:chat | device-cookie | not-in-handler | fresh-reauth | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/access/recovery/login | transport | none | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/access/passkey/register/options | ai:chat | device-cookie | not-in-handler | fresh-reauth | create_challenge | server/iphone_pwa.py |
| POST | /iphone/api/access/passkey/register/complete | ai:chat | device-cookie | not-in-handler | fresh-reauth | save_passkey | server/iphone_pwa.py |
| POST | /iphone/api/access/passkey/login/options | transport | none | not-in-handler | none-visible | create_challenge | server/iphone_pwa.py |
| POST | /iphone/api/access/passkey/login/complete | transport | none | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/enroll | transport | none | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/logout | none | device-cookie | not-in-handler | none-visible | delete_cookie | server/iphone_pwa.py |
| POST | /iphone/api/voice/turn | ai:chat | device-cookie | not-in-handler | mentions-approval | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/approval/{approval_id}/approve | ai:chat | device-cookie | not-in-handler | mentions-approval | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/approval/{approval_id}/reject | ai:chat | device-cookie | not-in-handler | mentions-approval | append, reject | server/iphone_pwa.py |
| GET | /iphone/api/conversations | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/conversations | ai:chat | device-cookie | not-in-handler | none-visible | create_thread | server/iphone_pwa.py |
| GET | /iphone/api/conversations/{conversation_id} | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/conversations/{conversation_id}/activate | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| PATCH | /iphone/api/conversations/{conversation_id} | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/voice/barge | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/voice/client-event | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/qualification/start | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/qualification/stop | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/qualification/takeover | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/iphone_pwa.py |
| GET | /iphone/api/qualification/sessions | ai:chat | device-cookie | not-in-handler | mentions-approval | none-visible | server/iphone_pwa.py |
| POST | /iphone/api/memory/candidates/{candidate_id}/approve | memory:write | trusted-session-or-device | not-in-handler | none-visible | audit | server/memory_governance_api.py |
| DELETE | /iphone/api/memory/candidates/{candidate_id} | memory:write | trusted-session-or-device | not-in-handler | none-visible | audit | server/memory_governance_api.py |
| GET | /iphone/api/memory/retrieval | memory:read | device-cookie | not-in-handler | none-visible | none-visible | server/memory_knowledge_inspection.py |
| GET | /iphone/api/life-graph | memory:read | device-cookie | not-in-handler | none-visible | none-visible | server/memory_knowledge_inspection.py |
| GET | /iphone/api/life-graph/timeline | memory:read | device-cookie | not-in-handler | none-visible | none-visible | server/memory_knowledge_inspection.py |
| GET | /iphone/api/memory/{memory_id}/retrieval-explanation | memory:read | device-cookie | not-in-handler | none-visible | none-visible | server/memory_knowledge_inspection.py |
| GET | /iphone/api/knowledge/ocr/status | knowledge:read | device-cookie | not-in-handler | none-visible | none-visible | server/memory_knowledge_inspection.py |
| GET | /iphone/api/knowledge/{document_id}/versions | knowledge:read | device-cookie | not-in-handler | none-visible | none-visible | server/memory_knowledge_inspection.py |
| DELETE | /iphone/api/knowledge/{document_id}/version | knowledge:write | device-cookie | not-in-handler | none-visible | delete_version | server/memory_knowledge_inspection.py |
| DELETE | /iphone/api/knowledge/lineages/{lineage_id} | knowledge:write | device-cookie | not-in-handler | none-visible | delete_lineage | server/memory_knowledge_inspection.py |
| GET | /iphone/api/world/observations | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/multimodal_world_api.py |
| GET | /iphone/api/world/observations/{observation_id} | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/multimodal_world_api.py |
| GET | /iphone/api/world/observations/{observation_id}/lineage | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/multimodal_world_api.py |
| DELETE | /iphone/api/world/observations/{observation_id} | memory:write | device-cookie | not-in-handler | none-visible | delete | server/multimodal_world_api.py |
| GET | /iphone/api/world/capabilities | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/multimodal_world_api.py |
| GET | /iphone/api/world/governed-context | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/multimodal_world_api.py |
| GET | /iphone/api/preferences | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| PUT | /iphone/api/preferences | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| GET | /iphone/api/memory | memory:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| GET | /iphone/api/memory/graph | memory:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| GET | /iphone/api/memory/tree | memory:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| GET | /iphone/api/memory/export | memory:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/memory/retention | memory:write | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/memory | memory:write | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| GET | /iphone/api/memory/{memory_id} | memory:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| PATCH | /iphone/api/memory/{memory_id} | memory:write | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| DELETE | /iphone/api/memory/{memory_id} | memory:write | device-cookie | not-in-handler | none-visible | delete | server/owner_product.py |
| GET | /iphone/api/knowledge | knowledge:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| GET | /iphone/api/knowledge/search | knowledge:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| GET | /iphone/api/knowledge/export | knowledge:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/knowledge | knowledge:write | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| GET | /iphone/api/knowledge/{document_id} | knowledge:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| PATCH | /iphone/api/knowledge/{document_id} | knowledge:write | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| DELETE | /iphone/api/knowledge/{document_id} | knowledge:write | device-cookie | not-in-handler | none-visible | delete | server/owner_product.py |
| GET | /iphone/api/activities | activities:read | device-cookie | not-in-handler | none-visible | audit_entries | server/owner_product.py |
| GET | /iphone/api/devices | device:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| PATCH | /iphone/api/devices/{target_device_id}/permissions | device:admin | device-cookie | not-in-handler | fresh-reauth | none-visible | server/owner_product.py |
| POST | /iphone/api/devices/{target_device_id}/revoke | device:admin | device-cookie | not-in-handler | fresh-reauth | revoke | server/owner_product.py |
| GET | /iphone/api/workflows | workflow:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/workflows | workflow:write | device-cookie | not-in-handler | none-visible | create_workflow | server/owner_product.py |
| POST | /iphone/api/workflows/{workflow_id}/run | workflow:write | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/workflows/runs/{run_id}/cancel | workflow:write | device-cookie | not-in-handler | fresh-reauth | none-visible | server/owner_product.py |
| POST | /iphone/api/workflows/runs/{run_id}/recovery/link | workflow:approve | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/workflows/runs/{run_id}/recovery/refresh | workflow:approve | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/workflows/runs/{run_id}/resume | workflow:write | device-cookie | not-in-handler | fresh-reauth | none-visible | server/owner_product.py |
| POST | /iphone/api/workflows/runs/{run_id}/approve | workflow:approve | device-cookie | not-in-handler | mentions-approval | approve_run | server/owner_product.py |
| POST | /iphone/api/workflows/runs/{run_id}/reject | workflow:approve | device-cookie | not-in-handler | fresh-reauth | reject_run | server/owner_product.py |
| POST | /iphone/api/system/emergency-stop | device:admin | device-cookie | checked-in-handler | fresh-reauth | set_emergency_stop | server/owner_product.py |
| GET | /iphone/api/qualification | qualification:read | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/qualification/stages | qualification:record | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/qualification/sessions/{session_id}/trials | qualification:record | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/qualification/sessions/{session_id}/finish | qualification:record | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| GET | /iphone/api/system/status | activities:read | device-cookie | checked-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/system/model-evaluation | qualification:record | device-cookie | not-in-handler | none-visible | none-visible | server/owner_product.py |
| POST | /iphone/api/operations/plans | ai:chat | device-cookie | not-in-handler | none-visible | create_plan | server/personal_operations_api.py |
| POST | /iphone/api/operations/from-everyday/{item_id} | ai:chat | device-cookie | not-in-handler | none-visible | create_from_everyday | server/personal_operations_api.py |
| POST | /iphone/api/operations/plans/{plan_id}/execute | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/personal_operations_api.py |
| GET | /iphone/api/operations/{operation_id} | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/personal_operations_api.py |
| POST | /iphone/api/operations/{operation_id}/approve | ai:chat | device-cookie | not-in-handler | none-visible | approve | server/personal_operations_api.py |
| POST | /iphone/api/operations/{operation_id}/reject | ai:chat | device-cookie | not-in-handler | none-visible | reject | server/personal_operations_api.py |
| POST | /iphone/api/operations/{operation_id}/cancel | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/personal_operations_api.py |
| POST | /iphone/api/operations/{operation_id}/recovery/link | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/personal_operations_api.py |
| POST | /iphone/api/operations/{operation_id}/recovery/refresh | ai:chat | device-cookie | not-in-handler | none-visible | none-visible | server/personal_operations_api.py |
| POST | /iphone/api/conversations/{conversation_id}/archive | trusted-session | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/pwa_conversations.py |
| DELETE | /iphone/api/conversations/{conversation_id} | trusted-session | trusted-session-or-device | not-in-handler | none-visible | delete_thread | server/pwa_conversations.py |
| GET | /iphone/api/conversations/{conversation_id}/export | trusted-session | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/pwa_conversations.py |
| POST | /iphone/api/access/reauth/password | trusted-session | trusted-session-or-device | not-in-handler | fresh-reauth | none-visible | server/pwa_security.py |
| GET | /iphone/api/sessions | trusted-session | trusted-session-or-device | not-in-handler | fresh-reauth | none-visible | server/pwa_security.py |
| POST | /iphone/api/sessions/{session_id}/revoke | trusted-session | trusted-session-or-device | not-in-handler | none-visible | revoke | server/pwa_security.py |
| POST | /iphone/api/sessions/revoke-others | trusted-session | trusted-session-or-device | not-in-handler | none-visible | revoke | server/pwa_security.py |
| GET | /iphone/api/execution-recovery/{transaction_id} | ai:chat | trusted-session-or-device | not-in-handler | none-visible | none-visible | server/recovery_visibility_api.py |
| GET | /iphone/api/workflows/runs/{run_id}/budget | workflow:read | device-cookie | not-in-handler | none-visible | none-visible | server/workflow_budget_api.py |
| POST | /iphone/api/workflows/runs/{run_id}/budget/override | workflow:approve | device-cookie | not-in-handler | fresh-reauth | none-visible | server/workflow_budget_api.py |

## Companions

The web companion in `web-companion/app.js` calls only cloud routes: `/cloud/session`, `/cloud/status`, `/cloud/events`, `/cloud/command`, `/cloud/approval`, `/cloud/memory/search`, and `/cloud/emergency-stop`. Those rows above are the authority. iOS and Android shells are not a second server authority in this census.

Private Knowledge is not granted by a companion call. Connector writes stay on `knowledge:write`, and `private` stays on `knowledge:private`.
