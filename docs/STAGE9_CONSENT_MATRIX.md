# Stage 9 consent matrix — partial

**Status:** WP4 started, not done.  
**Surface covered:** `server/owner_product.py` only.  
**Not covered:** control API `server/api.py`, connector routes, voice, cloud, companions.  
**Rule:** a row is a scope the handler asks `authenticate` for. It is not a new grant. Adding a scope here without a code change is a test failure, not a product change.

Private Knowledge is not a separate authenticate scope on these handlers. `knowledge_access` adds `private` only when the device already has `knowledge:private`. Emergency Stop on this surface asks for `device:admin`, not a dedicated stop scope. That is recorded, not widened.

| Route | Scope | Authority | File |
| --- | --- | --- | --- |
| GET /iphone/api/preferences | ai:chat | device session | server/owner_product.py |
| PUT /iphone/api/preferences | ai:chat | device session | server/owner_product.py |
| GET /iphone/api/memory | memory:read | memory | server/owner_product.py |
| POST /iphone/api/memory | memory:write | memory | server/owner_product.py |
| PATCH /iphone/api/memory/{memory_id} | memory:write | memory | server/owner_product.py |
| DELETE /iphone/api/memory/{memory_id} | memory:write | memory | server/owner_product.py |
| GET /iphone/api/knowledge | knowledge:read | knowledge | server/owner_product.py |
| POST /iphone/api/knowledge | knowledge:write | knowledge | server/owner_product.py |
| PATCH /iphone/api/knowledge/{document_id} | knowledge:write | knowledge | server/owner_product.py |
| DELETE /iphone/api/knowledge/{document_id} | knowledge:write | knowledge | server/owner_product.py |
| GET /iphone/api/devices | device:read | devices | server/owner_product.py |
| PATCH /iphone/api/devices/{target_device_id}/permissions | device:admin | devices | server/owner_product.py |
| POST /iphone/api/devices/{target_device_id}/revoke | device:admin | devices | server/owner_product.py |
| GET /iphone/api/workflows | workflow:read | automation | server/owner_product.py |
| POST /iphone/api/workflows | workflow:write | automation | server/owner_product.py |
| POST /iphone/api/workflows/{workflow_id}/run | workflow:write | automation | server/owner_product.py |
| POST /iphone/api/workflows/runs/{run_id}/approve | workflow:approve | approvals | server/owner_product.py |
| POST /iphone/api/system/emergency-stop | device:admin | tools runtime-controls | server/owner_product.py |

Connector Knowledge writes still require `knowledge:write`, and `private` requires `knowledge:private`, in `server/connector_knowledge_api.py`. They are not repeated as new rows until that file is rowed the same way.

This matrix does not satisfy the Stage 9 exit criterion for consent review.
