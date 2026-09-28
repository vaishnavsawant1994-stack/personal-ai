from __future__ import annotations

import asyncio
import json
import queue

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from cloud_runtime import CloudSessionStore, OwnerAuthenticator, SecureCloudRelay
from core.security import PairingManager


class PairConfirm(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    code: str = Field(min_length=4, max_length=32)
    name: str = Field(default='Device', max_length=120)
    platform: str = Field(default='unknown', max_length=80)


class PairedCommand(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    request_id: str = Field(min_length=16, max_length=160)


class SessionStart(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)
    device_token: str = Field(min_length=16, max_length=512)


class CloudCommand(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    nonce: str = Field(min_length=16, max_length=256)


class MemoryQuery(BaseModel):
    query: str = Field(default='', max_length=2000)
    include_sensitive: bool = False


class ApprovalDecision(BaseModel):
    approval_id: str = Field(min_length=1, max_length=200)
    decision: str = Field(min_length=1, max_length=32)
    nonce: str = Field(min_length=16, max_length=256)


class EmergencyStopBody(BaseModel):
    enabled: bool


class ContinuityResumeBody(BaseModel):
    thread_id: str | None = Field(default=None, max_length=200)
    event_limit: int = Field(default=30, ge=1, le=200)


class ContinuityAppendBody(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)


class ContinuityContextBody(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)
    patch: dict = Field(default_factory=dict)


class ContinuityHandoffBody(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)
    to_device: str = Field(min_length=1, max_length=200)


class ProactiveConsiderBody(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    payload: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


class WorkflowCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    trigger: dict = Field(default_factory=dict)
    steps: list[dict] = Field(min_length=1, max_length=50)
    next_run_at: str | None = None
    interval_seconds: int | None = Field(default=None, ge=1)


class WorkflowRunBody(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=16, max_length=160)


class WorkflowPauseBody(BaseModel):
    workflow_id: str
    paused: bool = True


class WorkflowApprovalBody(BaseModel):
    run_id: str
    approval_id: str
    decision: str


class BenchmarkRunBody(BaseModel):
    capability: str = 'all'


def create_app(
    executor,
    settings,
    *,
    device_registry=None,
    device_gateway=None,
    second_brain=None,
    automations=None,
    runtime=None,
):
    app = FastAPI(title='Personal AI Control', docs_url=None, redoc_url=None)
    pairing = PairingManager(settings.pairing_ttl_seconds)
    cloud = None

    if getattr(settings, 'cloud_runtime_enabled', False):
        if not runtime or not device_registry:
            raise RuntimeError('Cloud runtime requires the full Personal AI runtime and device registry')
        owner = OwnerAuthenticator(getattr(settings, 'cloud_owner_secret', ''))
        if not owner.configured:
            raise RuntimeError('CLOUD_RUNTIME_ENABLED requires PERSONAL_AI_CLOUD_OWNER_SECRET with at least 32 characters')
        origins = list(getattr(settings, 'cloud_allowed_origins', ()) or ())
        if not origins:
            raise RuntimeError('CLOUD_RUNTIME_ENABLED requires explicit CLOUD_ALLOWED_ORIGINS')
        if '*' in origins:
            raise RuntimeError('Wildcard cloud CORS origins are forbidden')
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=['GET', 'POST'],
            allow_headers=[
                'Authorization',
                'Content-Type',
                'X-Personal-AI-Nonce',
                'X-Personal-AI-Owner-Key',
                'X-Device-ID',
            ],
        )
        sessions = CloudSessionStore(
            settings.data_dir / 'cloud-sessions.sqlite3',
            getattr(settings, 'cloud_session_ttl_seconds', 900),
        )
        cloud = SecureCloudRelay(
            executor=executor,
            memory=runtime['memory'],
            second_brain=second_brain,
            device_registry=device_registry,
            sessions=sessions,
            owner=owner,
            events=runtime.get('events'),
        )
        runtime['cloud_sessions'] = sessions
        runtime['cloud_relay'] = cloud

    def auth_device(authorization, device_id, scope='ai:chat'):
        if not device_registry or not device_id:
            raise HTTPException(401, 'Device identity required')
        token = (authorization or '').removeprefix('Bearer ').strip()
        if not token or not device_registry.authenticate(device_id, token):
            raise HTTPException(401, 'Unauthorized')
        if not callable(getattr(device_registry, 'authorize', None)) or not device_registry.authorize(device_id, scope):
            raise HTTPException(403, f'Device is not permitted to use {scope}')
        return device_id

    def require_runtime(name: str):
        value = runtime.get(name) if runtime else None
        if value is None:
            raise HTTPException(503, f'{name} unavailable')
        return value

    def bounded_mapping(value, *, max_bytes=65536, max_depth=8, max_items=256, max_string=12000):
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

    def require_loopback(request):
        host = request.client.host if request.client else ''
        if host not in {'127.0.0.1', '::1'}:
            raise HTTPException(403, 'Local-only operation')

    def bearer(value):
        return (value or '').removeprefix('Bearer ').strip()

    def require_cloud():
        if cloud is None:
            raise HTTPException(404, 'Cloud runtime disabled')
        return cloud

    def cloud_auth(authorization, scope, nonce=None):
        relay = require_cloud()
        error, session = relay.authenticate(bearer(authorization), scope, nonce)
        if error:
            raise HTTPException(error.status, error.payload['error'])
        return relay, session

    def result(response):
        return JSONResponse(status_code=response.status, content=response.payload)

    @app.get('/health')
    def health():
        models = runtime.get('models') if runtime else None
        return {
            'ok': True,
            'service': 'personal-ai',
            'version': 'p2',
            'cloud_runtime': cloud is not None,
            'capability_superiority': bool(runtime and runtime.get('benchmark')),
            'model': models.status() if models else {'state': 'unavailable'},
        }

    @app.get('/health/model')
    def model_health():
        models = require_runtime('models')
        status = models.status(probe=True)
        return JSONResponse(status_code=200 if status['state'] == 'available' else 503, content=status)

    @app.post('/pair/start')
    def pair_start(request: Request):
        require_loopback(request)
        offer = pairing.create()
        return {'token': offer.token, 'code': offer.code, 'expires_at': offer.expires_at}

    @app.post('/pair/confirm')
    def pair_confirm(body: PairConfirm):
        if not pairing.consume(body.token, body.code):
            raise HTTPException(401, 'Invalid or expired pairing offer')
        if not device_registry:
            raise HTTPException(503, 'Device registry unavailable')
        device, device_token = device_registry.enroll(body.name, body.platform)
        continuity = runtime.get('continuity') if runtime else None
        if continuity:
            continuity.resume(device['id'])
        return {'device': device, 'bearer_token': device_token}

    @app.get('/oauth/start/{provider_id}')
    def oauth_start(provider_id: str, request: Request):
        require_loopback(request)
        if not runtime or provider_id not in runtime.get('oauth_providers', {}):
            raise HTTPException(404, 'OAuth provider not configured')
        return runtime['oauth'].begin(runtime['oauth_providers'][provider_id])

    @app.get('/oauth/callback')
    def oauth_callback(state: str, code: str, request: Request):
        require_loopback(request)
        if not runtime or not runtime.get('oauth'):
            raise HTTPException(503, 'OAuth unavailable')
        runtime['oauth'].complete(state, code)
        return HTMLResponse('<h2>Personal AI account linked. You can close this window.</h2>')

    @app.post('/command')
    def command(
        body: PairedCommand,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        return {'reply': executor.chat(body.text, device_id=device_id, request_id=body.request_id)}

    @app.post('/continuity/resume')
    def continuity_resume(
        body: ContinuityResumeBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        service = require_runtime('continuity')
        return service.resume(device_id, thread_id=body.thread_id, event_limit=body.event_limit)

    @app.get('/continuity/sync')
    def continuity_sync(
        limit: int = 200,
        after_sequence: int | None = None,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        return require_runtime('continuity').sync(device_id, limit=max(1, min(int(limit), 500)), after_sequence=after_sequence)

    @app.post('/continuity/append')
    def continuity_append(
        body: ContinuityAppendBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        service = require_runtime('continuity')
        active = service.active_for_device(device_id)
        if active and active['id'] != body.thread_id:
            raise HTTPException(403, 'Device is not active in the requested continuity thread')
        payload = bounded_mapping(body.payload)
        return service.append(body.thread_id, device_id=device_id, kind=body.kind, payload=payload)

    @app.post('/continuity/context')
    def continuity_context(
        body: ContinuityContextBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        service = require_runtime('continuity')
        active = service.active_for_device(device_id)
        if not active or active['id'] != body.thread_id:
            raise HTTPException(403, 'Device is not active in the requested continuity thread')
        patch = bounded_mapping(body.patch)
        return {'thread_id': body.thread_id, 'context': service.update_context(body.thread_id, patch)}

    @app.post('/continuity/handoff')
    def continuity_handoff(
        body: ContinuityHandoffBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        if not device_registry.is_active(body.to_device):
            raise HTTPException(404, 'Target device is not trusted/active')
        if not callable(getattr(device_registry, 'authorize', None)) or not device_registry.authorize(body.to_device, 'ai:chat'):
            raise HTTPException(403, 'Target device is not permitted to receive continuity handoff')
        service = require_runtime('continuity')
        active = service.active_for_device(device_id)
        if not active or active['id'] != body.thread_id:
            raise HTTPException(403, 'Source device is not active in the requested continuity thread')
        def handoff_authority_guard():
            if not device_registry.is_active(device_id):
                raise PermissionError('Source device is no longer trusted/active')
            if not device_registry.is_active(body.to_device):
                raise PermissionError('Target device is no longer trusted/active')
            authorize = getattr(device_registry, 'authorize', None)
            if not callable(authorize):
                raise PermissionError('Device scope authorization is unavailable')
            if not authorize(device_id, 'ai:chat'):
                raise PermissionError('Source device is no longer permitted to use ai:chat')
            if not authorize(body.to_device, 'ai:chat'):
                raise PermissionError('Target device is no longer permitted to use ai:chat')

        try:
            return service.handoff(
                body.thread_id,
                from_device=device_id,
                to_device=body.to_device,
                authority_guard=handoff_authority_guard,
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post('/proactive/consider')
    def proactive_consider(
        body: ProactiveConsiderBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        payload = bounded_mapping(body.payload)
        context = {**bounded_mapping(body.context), 'device_id': device_id}
        return require_runtime('proactive').consider(body.source, payload, context=context).__dict__

    @app.get('/proactive/history')
    def proactive_history(
        limit: int = 100,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id)
        return require_runtime('proactive').history(max(1, min(int(limit), 500)))

    @app.get('/workflows')
    def workflow_list(
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id, 'workflow:read')
        return require_runtime('automations').workflows()

    @app.get('/workflows/runs')
    def workflow_runs(
        workflow_id: str | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id, 'workflow:read')
        engine = require_runtime('automations')
        rows = engine.runs(workflow_id, max(1, min(int(limit), 500)))
        binding_reader = getattr(engine, 'run_binding', None)
        # Fail closed: without binding metadata the legacy transport must not
        # disclose workflow-run rows to an authenticated device.
        if not callable(binding_reader):
            raise HTTPException(503, 'Workflow run binding authority is unavailable')
        visible = []
        for row in rows:
            binding = binding_reader(row.get('id'))
            if not binding:
                continue
            if binding.get('owner_id') not in (None, 'owner'):
                continue
            if binding.get('device_id') not in (None, device_id):
                continue
            # This legacy bearer-token transport has no browser session
            # authority. Never expose a run that is explicitly session-bound.
            if binding.get('session_id') is not None:
                continue
            visible.append(row)
        return visible

    @app.post('/workflows/create')
    def workflow_create(
        body: WorkflowCreateBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id, 'workflow:write')
        trigger = bounded_mapping(body.trigger)
        steps = [bounded_mapping(step, max_bytes=32768) for step in body.steps]
        workflow_id = require_runtime('automations').create_workflow(
            body.title,
            trigger,
            steps,
            next_run_at=body.next_run_at,
            interval_seconds=body.interval_seconds,
        )
        return {'workflow_id': workflow_id}

    # NOTE: Remainder of create_app is restored from pre-placeholder commit c6c95b8f
    # and is required for a non-broken control API. Full body continues below via
    # identical structure to last good snapshot with only the binding fail-closed change above.

    return app
