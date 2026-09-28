from __future__ import annotations

import base64
import binascii
import json
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from knowledge.store import KnowledgeError
from memory.second_brain import MemoryCandidate
from security.request_context import current_trusted_request


class MemoryCreateBody(BaseModel):
    type: str = Field(default='note', min_length=1, max_length=60)
    subject: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=20000)
    source: str = Field(default='explicit-owner', max_length=240)
    confidence: float = Field(default=1.0, ge=0, le=1)
    verified: bool = True
    sensitivity: Literal['normal', 'sensitive', 'secret', 'never_store'] = 'normal'
    tags: list[str] = Field(default_factory=list, max_length=50)
    importance: float = Field(default=.7, ge=0, le=1)
    occurred_at: str | None = None
    parent_id: str | None = None


class MemoryUpdateBody(BaseModel):
    type: str | None = Field(default=None, max_length=60)
    subject: str | None = Field(default=None, max_length=240)
    content: str | None = Field(default=None, max_length=20000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    verified: bool | None = None
    sensitivity: Literal['normal', 'sensitive', 'secret', 'never_store'] | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    importance: float | None = Field(default=None, ge=0, le=1)
    occurred_at: str | None = None
    parent_id: str | None = None


class RetentionBody(BaseModel):
    older_than_days: int = Field(ge=1, le=36500)
    sensitivity: Literal['normal', 'sensitive', 'secret'] | None = None
    confirm_delete: bool = False


class KnowledgeUploadBody(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    title: str | None = Field(default=None, max_length=240)
    media_type: str = Field(default='application/octet-stream', max_length=160)
    source: str = Field(default='owner-upload', max_length=500)
    access_class: Literal['owner', 'trusted-devices', 'private'] = 'owner'
    content_base64: str | None = Field(default=None, max_length=14_000_000)
    text: str | None = Field(default=None, max_length=10_000_000)
    metadata: dict = Field(default_factory=dict)


class KnowledgeUpdateBody(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    source: str | None = Field(default=None, max_length=500)
    access_class: Literal['owner', 'trusted-devices', 'private'] | None = None
    metadata: dict | None = None


class DevicePermissionsBody(BaseModel):
    scopes: list[str] = Field(max_length=30)


class ConfirmBody(BaseModel):
    confirm: Literal[True]


class QualificationSessionBody(BaseModel):
    stage: Literal['P3.2', 'P3.3', 'P3.4', 'P3.5', 'P3.6', 'P3.7', 'P3.8']
    evidence_class: Literal['real_device', 'production_like', 'competitive']
    environment: dict = Field(default_factory=dict)


class QualificationTrialBody(BaseModel):
    task: str = Field(min_length=1, max_length=240)
    passed: bool
    latency_ms: float | None = Field(default=None, ge=0)
    metrics: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


class QualificationFinishBody(BaseModel):
    duration_seconds: float | None = Field(default=None, ge=0)


class WorkflowCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    trigger: dict = Field(default_factory=lambda: {'type': 'manual'})
    steps: list[dict] = Field(min_length=1, max_length=50)
    next_run_at: str | None = None
    interval_seconds: int | None = Field(default=None, ge=1)


class WorkflowRunBody(BaseModel):
    context: dict = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=16, max_length=160)


class EmergencyStopBody(BaseModel):
    enabled: bool


class UiPreferencesBody(BaseModel):
    continuous_voice: bool = True
    voice_rate: float = Field(default=1.0, ge=0.75, le=1.35)
    quiet_hours: bool = True


def _bounded_mapping(value, *, max_bytes=65536, max_depth=8, max_items=256, max_string=12000):
    if not isinstance(value, dict):
        raise HTTPException(422, 'Expected a JSON object')
    nodes = 0
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            raise HTTPException(413, 'JSON object nesting exceeds limit')
        if isinstance(current, dict):
            if len(current) > max_items:
                raise HTTPException(413, 'JSON object contains too many fields')
            for key, child in current.items():
                if len(str(key)) > 256:
                    raise HTTPException(413, 'JSON object key is too long')
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            if len(current) > max_items:
                raise HTTPException(413, 'JSON collection contains too many items')
            for child in current:
                stack.append((child, depth + 1))
        elif isinstance(current, str) and len(current) > max_string:
            raise HTTPException(413, 'JSON string exceeds limit')
        nodes += 1
        if nodes > 4096:
            raise HTTPException(413, 'JSON object is too complex')
    try:
        encoded = json.dumps(value, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, 'JSON object contains unsupported values') from exc
    if len(encoded) > max_bytes:
        raise HTTPException(413, 'JSON object exceeds maximum size')
    return value


def owner_product_router(runtime):
    router = APIRouter(prefix='/iphone/api', tags=['owner-product'])
    registry = runtime['device_registry']
    memory = runtime['memory']
    second_brain = runtime['second_brain']
    knowledge = runtime['knowledge']

    def authenticate(device_id: str | None, token: str | None, scope: str):
        if not device_id or not token or not registry.authenticate(device_id, token):
            raise HTTPException(401, 'This browser is not trusted or its session was revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, scope):
            raise HTTPException(403, f'This device is not permitted to use {scope}')
        return device_id

    def audit(action: str, *, device_id: str, **payload):
        memory.audit('owner-product', action, {'device_id': device_id, **payload})

    def require_fresh_reauthentication():
        context = current_trusted_request()
        ttl = int(getattr(runtime.get('agent_executor'), 'reauth_ttl_seconds', 300) or 300)
        ttl = max(30, min(ttl, 900))
        stamp = getattr(context, 'reauthenticated_at', None) if context is not None else None
        try:
            age = time.time() - float(stamp)
        except (TypeError, ValueError):
            age = ttl + 1
        if context is None or age < 0 or age > ttl:
            raise HTTPException(401, {
                'code': 'reauthentication_required',
                'message': 'Fresh owner verification is required for this security-sensitive action.',
            })
        return context

    def workflow_authority(device_id: str):
        context = current_trusted_request()
        if context is not None and context.device_id != device_id:
            raise HTTPException(403, 'Authenticated browser session does not match this device')
        return {
            'owner_id': 'owner',
            'device_id': device_id,
            'session_id': context.session_id if context is not None else None,
            'reauthenticated_at': context.reauthenticated_at if context is not None else None,
        }

    def workflow_binding_matches(engine, run_id: str, auth: dict) -> bool:
        reader = getattr(engine, 'run_binding', None)
        if not callable(reader):
            return False
        binding = reader(run_id)
        if not binding:
            return False
        return (
            binding.get('owner_id') in (None, auth['owner_id'])
            and binding.get('device_id') in (None, auth['device_id'])
            and binding.get('session_id') in (None, auth['session_id'])
        )

    def knowledge_access(device_id: str):
        classes = {'owner', 'trusted-devices'}
        if not hasattr(registry, 'authorize') or registry.authorize(device_id, 'knowledge:private'):
            classes.add('private')
        return classes

    def ui_preferences(device_id: str):
        defaults = UiPreferencesBody().model_dump()
        try:
            stored = json.loads(registry.metadata(device_id).get('ui.preferences', '{}'))
        except (TypeError, ValueError, json.JSONDecodeError):
            stored = {}
        try:
            return UiPreferencesBody(**{**defaults, **stored}).model_dump()
        except (TypeError, ValueError):
            return defaults

    @router.get('/preferences')
    def preferences_get(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        return ui_preferences(device_id)

    @router.put('/preferences')
    def preferences_update(
        body: UiPreferencesBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        value = body.model_dump()
        if not registry.set_metadata(device_id, 'ui.preferences', json.dumps(value, separators=(',', ':'))):
            raise HTTPException(404, 'Active device not found')
        audit('device.preferences.updated', device_id=device_id)
        return value

    def can_read_sensitive_memory(device_id: str):
        return not hasattr(registry, 'authorize') or registry.authorize(device_id, 'memory:sensitive')

    def filter_memories(rows, device_id: str):
        if can_read_sensitive_memory(device_id):
            return rows
        return [row for row in rows if str(row.get('sensitivity', 'normal')) not in {'sensitive', 'secret'}]

    def filter_tree(rows, device_id: str):
        output = []
        for row in rows:
            children = filter_tree(row.get('children', []), device_id)
            if can_read_sensitive_memory(device_id) or str(row.get('sensitivity', 'normal')) not in {'sensitive', 'secret'}:
                output.append({**row, 'children': children})
            else:
                output.extend(children)
        return output

    @router.get('/memory')
    def memory_list(
        q: str = '',
        limit: int = 100,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        rows = second_brain.context(q, min(limit, 100)) if q.strip() else memory.temporal_search(limit=min(limit, 100))
        return {'memories': filter_memories(rows, device_id)}

    @router.get('/memory/graph')
    def memory_graph(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        graph = second_brain.graph()
        nodes = filter_memories(graph.get('nodes', []), device_id)
        ids = {row['id'] for row in nodes}
        return {'nodes': nodes, 'edges': [edge for edge in graph.get('edges', []) if edge['source_id'] in ids and edge['target_id'] in ids]}

    @router.get('/memory/tree')
    def memory_tree(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        return {'roots': filter_tree(memory.tree(), device_id)}

    @router.get('/memory/export')
    def memory_export(
        include_sensitive: bool = True,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        if include_sensitive and not can_read_sensitive_memory(device_id):
            raise HTTPException(403, 'This device cannot export sensitive memory')
        audit('memory.exported', device_id=device_id, include_sensitive=include_sensitive)
        return memory.export(include_sensitive=include_sensitive)

    @router.post('/memory/retention')
    def memory_retention(
        body: RetentionBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        if body.sensitivity in {'sensitive', 'secret'} and not can_read_sensitive_memory(device_id):
            raise HTTPException(403, 'This device cannot create sensitive memory')
        result = second_brain.apply_retention(
            older_than_days=body.older_than_days,
            sensitivity=body.sensitivity,
            dry_run=not body.confirm_delete,
        )
        audit('memory.retention', device_id=device_id, matched=result['matched'], deleted=body.confirm_delete)
        return result

    @router.post('/memory')
    def memory_create(
        body: MemoryCreateBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        if body.sensitivity == 'never_store':
            raise HTTPException(409, 'NEVER_STORE content cannot be written to durable memory')
        if body.sensitivity in {'sensitive', 'secret'} and not can_read_sensitive_memory(device_id):
            raise HTTPException(403, 'This device cannot create sensitive memory')
        memory_id = second_brain.remember(MemoryCandidate(
            type=body.type,
            subject=body.subject,
            content=body.content,
            confidence=body.confidence,
            source=body.source,
            verified=body.verified,
            tags=body.tags,
            importance=body.importance,
            sensitivity=body.sensitivity,
            occurred_at=body.occurred_at,
        ))
        if body.parent_id:
            memory.update_memory(memory_id, parent_id=body.parent_id)
        audit('memory.created', device_id=device_id, memory_id=memory_id)
        return second_brain.memory_detail(memory_id)

    @router.get('/memory/{memory_id}')
    def memory_detail(memory_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        detail = second_brain.memory_detail(memory_id)
        if not detail or not filter_memories([detail], device_id):
            raise HTTPException(404, 'Memory not found')
        return detail

    @router.patch('/memory/{memory_id}')
    def memory_update(
        memory_id: str,
        body: MemoryUpdateBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        existing = memory.get(memory_id)
        if not existing or not filter_memories([existing], device_id):
            raise HTTPException(404, 'Memory not found')
        if body.sensitivity == 'never_store':
            raise HTTPException(409, 'Delete this memory instead of marking durable content NEVER_STORE')
        if body.sensitivity in {'sensitive', 'secret'} and not can_read_sensitive_memory(device_id):
            raise HTTPException(403, 'This device cannot mark memory sensitive')
        changes = body.model_dump(exclude_none=True)
        if not memory.update_memory(memory_id, **changes):
            raise HTTPException(404, 'Memory not found or no supported changes supplied')
        audit('memory.corrected', device_id=device_id, memory_id=memory_id, fields=sorted(changes))
        return second_brain.memory_detail(memory_id)

    @router.delete('/memory/{memory_id}')
    def memory_delete(
        memory_id: str,
        confirm: bool = False,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        if not confirm:
            raise HTTPException(409, 'Memory deletion requires confirm=true')
        existing = memory.get(memory_id)
        if not existing or not filter_memories([existing], device_id):
            raise HTTPException(404, 'Memory not found')
        if not second_brain.delete(memory_id):
            raise HTTPException(404, 'Memory not found')
        audit('memory.deleted', device_id=device_id, memory_id=memory_id)
        return {'ok': True, 'memory_id': memory_id}

    @router.get('/knowledge')
    def knowledge_list(
        q: str = '',
        limit: int = 100,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        return {'documents': knowledge.list(q, limit=min(limit, 100), access_classes=knowledge_access(device_id))}

    @router.get('/knowledge/search')
    def knowledge_search(
        q: str,
        limit: int = 12,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        return {'results': knowledge.search(q, limit=min(limit, 50), access_classes=knowledge_access(device_id))}

    @router.get('/knowledge/export')
    def knowledge_export(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        audit('knowledge.exported', device_id=device_id)
        return knowledge.export(access_classes=knowledge_access(device_id))

    @router.post('/knowledge')
    def knowledge_upload(
        body: KnowledgeUploadBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        if body.access_class == 'private' and 'private' not in knowledge_access(device_id):
            raise HTTPException(403, 'This device cannot create private knowledge')
        try:
            if body.content_base64 is not None:
                data = base64.b64decode(body.content_base64, validate=True)
            elif body.text is not None:
                data = body.text.encode('utf-8')
            else:
                raise KnowledgeError('File content is required')
            document = knowledge.ingest(
                filename=body.filename,
                data=data,
                title=body.title,
                media_type=body.media_type,
                source=body.source,
                access_class=body.access_class,
                metadata=_bounded_mapping(body.metadata),
            )
        except (KnowledgeError, binascii.Error) as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('knowledge.ingested', device_id=device_id, document_id=document['id'], checksum=document['checksum'])
        return document

    @router.get('/knowledge/{document_id}')
    def knowledge_detail(document_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        document = knowledge.detail(document_id)
        if not document or document['access_class'] not in knowledge_access(device_id):
            raise HTTPException(404, 'Knowledge document not found')
        return document

    @router.patch('/knowledge/{document_id}')
    def knowledge_update(
        document_id: str,
        body: KnowledgeUpdateBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        existing = knowledge.detail(document_id)
        if not existing or existing['access_class'] not in knowledge_access(device_id):
            raise HTTPException(404, 'Knowledge document not found')
        if body.access_class == 'private' and 'private' not in knowledge_access(device_id):
            raise HTTPException(403, 'This device cannot mark knowledge private')
        try:
            changes = body.model_dump(exclude_none=True)
            if 'metadata' in changes:
                changes['metadata'] = _bounded_mapping(changes['metadata'])
            document = knowledge.update(document_id, **changes)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except KnowledgeError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('knowledge.updated', device_id=device_id, document_id=document_id)
        return document

    @router.delete('/knowledge/{document_id}')
    def knowledge_delete(
        document_id: str,
        confirm: bool = False,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        if not confirm:
            raise HTTPException(409, 'Knowledge deletion requires confirm=true')
        existing = knowledge.detail(document_id)
        if not existing or existing['access_class'] not in knowledge_access(device_id):
            raise HTTPException(404, 'Knowledge document not found')
        if not knowledge.delete(document_id):
            raise HTTPException(404, 'Knowledge document not found')
        audit('knowledge.deleted', device_id=device_id, document_id=document_id)
        return {'ok': True, 'document_id': document_id}

    @router.get('/activities')
    def activities(
        category: str | None = None,
        limit: int = 200,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, 'activities:read')
        return {'activities': memory.audit_entries(category, min(limit, 500))}

    @router.get('/devices')
    def devices(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'device:read')
        return {'current_device_id': device_id, 'devices': registry.list()}

    @router.patch('/devices/{target_device_id}/permissions')
    def device_permissions(
        target_device_id: str,
        body: DevicePermissionsBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'device:admin')
        require_fresh_reauthentication()
        try:
            result = registry.set_permissions(target_device_id, body.scopes)
            cancelled_turns = cancelled_workflows = 0
            granted_scopes = set(result.get('scopes') or ())
            if 'ai:chat' not in granted_scopes:
                executor = runtime.get('executor')
                cancel_device_turns = getattr(executor, 'cancel_device_turns', None)
                if callable(cancel_device_turns):
                    cancelled_turns = int(cancel_device_turns(target_device_id, reason='device_permission_revoked'))
            if 'workflow:write' not in granted_scopes:
                automations = runtime.get('automations')
                cancel_device_runs = getattr(automations, 'cancel_device_runs', None)
                if callable(cancel_device_runs):
                    cancelled_workflows = int(cancel_device_runs(target_device_id, reason='workflow_permission_revoked'))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('device.permissions.updated', device_id=device_id, target_device_id=target_device_id, scopes=result['scopes'], cancelled_turns=cancelled_turns, cancelled_workflows=cancelled_workflows)
        return {**result, 'cancelled_turns': cancelled_turns, 'cancelled_workflows': cancelled_workflows}

    @router.post('/devices/{target_device_id}/revoke')
    def device_revoke(
        target_device_id: str,
        body: ConfirmBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'device:admin')
        require_fresh_reauthentication()
        if not registry.revoke(target_device_id):
            raise HTTPException(404, 'Device not found')
        revoked_sessions = {}
        for key in ('pwa_sessions', 'cloud_sessions'):
            store = runtime.get(key)
            revoke_device = getattr(store, 'revoke_device', None)
            if callable(revoke_device):
                revoked_sessions[key] = int(revoke_device(target_device_id))
        gateway = runtime.get('device_gateway')
        if gateway is not None:
            gateway.disconnect(target_device_id)
        executor = runtime.get('executor')
        cancel_device_turns = getattr(executor, 'cancel_device_turns', None)
        cancelled_turns = int(cancel_device_turns(target_device_id, reason='device_revoked')) if callable(cancel_device_turns) else 0
        automations = runtime.get('automations')
        cancel_device_runs = getattr(automations, 'cancel_device_runs', None)
        cancelled_workflows = int(cancel_device_runs(target_device_id, reason='device_revoked')) if callable(cancel_device_runs) else 0
        audit(
            'device.revoked',
            device_id=device_id,
            target_device_id=target_device_id,
            revoked_sessions=revoked_sessions,
            cancelled_turns=cancelled_turns,
            cancelled_workflows=cancelled_workflows,
        )
        return {
            'ok': True,
            'revoked_device_id': target_device_id,
            'current_device_revoked': target_device_id == device_id,
            'revoked_sessions': revoked_sessions,
            'cancelled_turns': cancelled_turns,
            'cancelled_workflows': cancelled_workflows,
        }

    @router.get('/workflows')
    def workflows(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:read')
        engine = runtime['automations']
        auth = workflow_authority(device_id)
        runs = [
            row for row in engine.runs(limit=100)
            if workflow_binding_matches(engine, row.get('id'), auth)
        ]
        return {'workflows': engine.workflows(), 'runs': runs}

    @router.post('/workflows')
    def workflow_create(body: WorkflowCreateBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            trigger = _bounded_mapping(body.trigger)
            steps = [_bounded_mapping(step, max_bytes=32768) for step in body.steps]
            workflow_id = runtime['automations'].create_workflow(
                body.title, trigger, steps,
                next_run_at=body.next_run_at, interval_seconds=body.interval_seconds,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('workflow.created', device_id=device_id, workflow_id=workflow_id)
        return runtime['automations'].workflow(workflow_id)

    @router.post('/workflows/{workflow_id}/run')
    def workflow_run(workflow_id: str, body: WorkflowRunBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            context = _bounded_mapping(body.context)
            run_id = runtime['automations'].run_workflow(
                workflow_id,
                context=context,
                background=True,
                idempotency_key=body.idempotency_key,
                **workflow_authority(device_id),
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        audit('workflow.started', device_id=device_id, workflow_id=workflow_id, run_id=run_id)
        return {'workflow_id': workflow_id, 'run_id': run_id, 'status': 'queued'}

    @router.post('/workflows/runs/{run_id}/cancel')
    def workflow_cancel(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            authority = workflow_authority(device_id)
            authority.pop('reauthenticated_at', None)
            result = runtime['automations'].cancel_run(run_id, **authority)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        audit('workflow.cancelled', device_id=device_id, run_id=run_id)
        return result

    @router.post('/workflows/runs/{run_id}/recovery/link')
    def workflow_recovery_link(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:approve')
        try: result = runtime['automations'].link_recovery(run_id, **workflow_authority(device_id))
        except KeyError as exc: raise HTTPException(404, 'Workflow run not found') from exc
        except (RuntimeError, PermissionError) as exc: raise HTTPException(409, str(exc)) from exc
        audit('workflow.recovery_linked', device_id=device_id, run_id=run_id, recovery_transaction_id=result['recovery_transaction_id'])
        return result

    @router.post('/workflows/runs/{run_id}/recovery/refresh')
    def workflow_recovery_refresh(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:approve')
        try: return runtime['automations'].refresh_recovery(run_id, **workflow_authority(device_id))
        except KeyError as exc: raise HTTPException(404, 'Workflow run not found') from exc
        except (RuntimeError, PermissionError) as exc: raise HTTPException(409, str(exc)) from exc

    @router.post('/workflows/runs/{run_id}/resume')
    def workflow_resume(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            authority = workflow_authority(device_id)
            authority.pop('reauthenticated_at', None)
            result = runtime['automations'].resume_run(run_id, **authority)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        audit('workflow.resumed', device_id=device_id, run_id=run_id)
        return result

    @router.post('/workflows/runs/{run_id}/approve')
    def workflow_approve(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:approve')
        engine = runtime['automations']
        auth = workflow_authority(device_id)
        if not workflow_binding_matches(engine, run_id, auth):
            raise HTTPException(403, 'Workflow authority mismatch')
        try:
            run = engine._run(run_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        approval_id = run.get('pending_approval_id')
        if not approval_id:
            raise HTTPException(409, 'Workflow is not waiting for approval')
        try:
            result = engine.approve_run(
                run_id,
                approval_id,
                **auth,
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        audit('workflow.approved', device_id=device_id, run_id=run_id, approval_id=approval_id)
        return result

    @router.post('/workflows/runs/{run_id}/reject')
    def workflow_reject(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:approve')
        engine = runtime['automations']
        authority = workflow_authority(device_id)
        if not workflow_binding_matches(engine, run_id, authority):
            raise HTTPException(403, 'Workflow authority mismatch')
        try:
            run = engine._run(run_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        approval_id = run.get('pending_approval_id')
        if not approval_id:
            raise HTTPException(409, 'Workflow is not waiting for approval')
        try:
            authority.pop('reauthenticated_at', None)
            result = engine.reject_run(run_id, approval_id, **authority)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        audit('workflow.rejected', device_id=device_id, run_id=run_id, approval_id=approval_id)
        return result

    @router.post('/system/emergency-stop')
    def emergency_stop(body: EmergencyStopBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'device:admin')
        if not body.enabled:
            require_fresh_reauthentication()
        runtime['tools'].set_emergency_stop(body.enabled)
        # ToolRegistry is the canonical E-stop authority and advances the
        # security epoch. Also cancel active canonical turns so this owner
        # surface converges with the cloud owner E-stop semantics.
        executor = runtime.get('executor')
        if body.enabled and executor is not None and hasattr(executor, 'cancel_active_turns'):
            executor.cancel_active_turns(reason='emergency_stop')
        events = runtime.get('events')
        if events is not None:
            events.emit('emergency.stop', enabled=body.enabled)
        autonomy = runtime.get('advanced_autonomy')
        if autonomy is not None:
            autonomy.emergency_stop('owner requested from trusted device') if body.enabled else autonomy.clear_emergency_stop()
        audit('system.emergency_stop', device_id=device_id, enabled=body.enabled)
        return {'enabled': body.enabled, 'message': 'All tool actions stopped' if body.enabled else 'Tool actions enabled'}

    @router.get('/qualification')
    def qualification_status(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, 'qualification:read')
        return runtime['p3_qualification'].status()

    @router.post('/qualification/stages')
    def qualification_start(
        body: QualificationSessionBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'qualification:record')
        environment = {**_bounded_mapping(body.environment), 'device_id': device_id, 'surface': 'ios-pwa'}
        try:
            session_id = runtime['p3_qualification'].start_session(
                body.stage,
                evidence_class=body.evidence_class,
                environment=environment,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('qualification.session.started', device_id=device_id, session_id=session_id, stage=body.stage)
        return {'session_id': session_id, 'stage': body.stage, 'evidence_class': body.evidence_class}

    @router.post('/qualification/sessions/{session_id}/trials')
    def qualification_trial(
        session_id: str,
        body: QualificationTrialBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'qualification:record')
        evidence = {**_bounded_mapping(body.evidence), 'device_id': device_id}
        metrics = _bounded_mapping(body.metrics)
        try:
            trial = runtime['p3_qualification'].record_trial(
                session_id,
                body.task,
                passed=body.passed,
                latency_ms=body.latency_ms,
                metrics=metrics,
                evidence=evidence,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'trial': trial, 'session_id': session_id}

    @router.post('/qualification/sessions/{session_id}/finish')
    def qualification_finish(
        session_id: str,
        body: QualificationFinishBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'qualification:record')
        try:
            result = runtime['p3_qualification'].finish_session(session_id, duration_seconds=body.duration_seconds)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('qualification.session.finished', device_id=device_id, session_id=session_id)
        return result

    @router.get('/system/status')
    def system_status(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, 'activities:read')
        return {
            'model': runtime['models'].status(),
            'tools': [
                {'name': tool.name, 'description': tool.description, 'risk': tool.risk.name}
                for tool in runtime['tools'].all()
            ],
            'integrations': runtime['integrations'].list(),
            'future_intelligence': runtime['future_intelligence'].status(),
            'emergency_stop': bool(getattr(runtime['tools'], 'emergency_stop', False)),
            'model_evaluation': runtime['model_evaluation'].latest(),
        }

    @router.post('/system/model-evaluation')
    def run_model_evaluation(
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'qualification:record')
        result = runtime['model_evaluation'].run()
        audit('model.evaluation.requested', device_id=device_id, run_id=result['id'])
        return result

    return router
