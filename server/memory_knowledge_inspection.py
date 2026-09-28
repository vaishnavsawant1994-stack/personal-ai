from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Query


def memory_knowledge_inspection_router(runtime):
    """Owner inspection APIs for retrieval explanations and knowledge lineage."""
    router = APIRouter(prefix='/iphone/api', tags=['memory-knowledge-inspection'])
    registry = runtime['device_registry']
    memory = runtime['memory']
    second_brain = runtime['second_brain']
    knowledge = runtime['knowledge']
    second_brain_life_graph = runtime.get('second_brain_life_graph')

    def authenticate(device_id: str | None, token: str | None, scope: str):
        if not device_id or not token or not registry.authenticate(device_id, token):
            raise HTTPException(401, 'This browser is not trusted or its session was revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, scope):
            raise HTTPException(403, f'This device is not permitted to use {scope}')
        return device_id

    def can_read_sensitive_memory(device_id: str):
        return not hasattr(registry, 'authorize') or registry.authorize(device_id, 'memory:sensitive')

    def allowed_memory_sensitivities(device_id: str):
        allowed = {'normal'}
        if can_read_sensitive_memory(device_id):
            allowed.update({'sensitive', 'secret'})
        return allowed

    def knowledge_access(device_id: str):
        classes = {'owner', 'trusted-devices'}
        if not hasattr(registry, 'authorize') or registry.authorize(device_id, 'knowledge:private'):
            classes.add('private')
        return classes

    def audit(action: str, *, device_id: str, **payload):
        memory.audit('owner-product', action, {'device_id': device_id, **payload})

    @router.get('/memory/retrieval')
    def memory_retrieval(q: str = Query(min_length=1, max_length=2000), limit: int = Query(default=20, ge=1, le=100), pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        rows = second_brain.context(q, limit, allowed_sensitivities=allowed_memory_sensitivities(device_id))
        audit('memory.retrieval.inspected', device_id=device_id, query_length=len(q), count=len(rows))
        return {'query': q, 'memories': rows}

    @router.get('/life-graph')
    def life_graph_snapshot(
        node_type: str | None = Query(default=None, max_length=64),
        limit: int = Query(default=100, ge=1, le=500),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        if second_brain_life_graph is None:
            raise HTTPException(503, 'Second Brain Life Graph integration is unavailable')
        payload = second_brain_life_graph.graph(
            type=node_type,
            limit=limit,
            allowed_sensitivities=allowed_memory_sensitivities(device_id),
        )
        audit(
            'life_graph.inspected',
            device_id=device_id,
            node_type=node_type,
            node_count=len(payload.get('nodes', [])),
            edge_count=len(payload.get('edges', [])),
        )
        return payload

    @router.get('/life-graph/timeline')
    def life_graph_timeline(
        limit: int = Query(default=100, ge=1, le=500),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        if second_brain_life_graph is None:
            raise HTTPException(503, 'Second Brain Life Graph integration is unavailable')
        payload = second_brain_life_graph.timeline(
            limit=limit,
            allowed_sensitivities=allowed_memory_sensitivities(device_id),
        )
        audit('life_graph.timeline.inspected', device_id=device_id, count=len(payload.get('items', [])))
        return payload

    @router.get('/memory/{memory_id}/retrieval-explanation')
    def memory_retrieval_explanation(memory_id: str, q: str = Query(min_length=1, max_length=2000), pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        explanation = second_brain.explain_retrieval(memory_id, q, allowed_sensitivities=allowed_memory_sensitivities(device_id))
        if explanation is None:
            raise HTTPException(404, 'This memory was not retrieved for the supplied query')
        audit('memory.retrieval.explanation', device_id=device_id, memory_id=memory_id, query_length=len(q))
        return explanation

    @router.get('/knowledge/ocr/status')
    def knowledge_ocr_status(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, 'knowledge:read')
        return knowledge.ocr_status()

    @router.get('/knowledge/{document_id}/versions')
    def knowledge_versions(document_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        versions = knowledge.history(document_id, access_classes=knowledge_access(device_id))
        if not versions:
            raise HTTPException(404, 'Knowledge document lineage not found')
        return {'lineage_id': versions[0]['lineage_id'], 'versions': versions}

    @router.delete('/knowledge/{document_id}/version')
    def knowledge_delete_version(document_id: str, confirm: bool = False, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        if not confirm:
            raise HTTPException(409, 'Knowledge version deletion requires confirm=true')
        existing = knowledge.detail(document_id)
        if not existing or existing['access_class'] not in knowledge_access(device_id):
            raise HTTPException(404, 'Knowledge document version not found')
        if not knowledge.delete_version(document_id):
            raise HTTPException(404, 'Knowledge document version not found')
        audit('knowledge.version.deleted', device_id=device_id, document_id=document_id, lineage_id=existing['lineage_id'], version=existing['version'])
        return {'ok': True, 'document_id': document_id, 'lineage_id': existing['lineage_id'], 'deleted_version': existing['version']}

    @router.delete('/knowledge/lineages/{lineage_id}')
    def knowledge_delete_lineage(lineage_id: str, confirm: bool = False, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        if not confirm:
            raise HTTPException(409, 'Knowledge lineage deletion requires confirm=true')
        all_versions = knowledge.history(lineage_id)
        visible = knowledge.history(lineage_id, access_classes=knowledge_access(device_id))
        if not all_versions or len(visible) != len(all_versions):
            raise HTTPException(404, 'Knowledge document lineage not found')
        count = knowledge.delete_lineage(lineage_id)
        audit('knowledge.lineage.deleted', device_id=device_id, lineage_id=lineage_id, versions=count)
        return {'ok': True, 'lineage_id': lineage_id, 'deleted_versions': count}

    return router
