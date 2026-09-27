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
    token: str
    code: str
    name: str = 'Device'
    platform: str = 'unknown'


class PairedCommand(BaseModel):
    text: str


class SessionStart(BaseModel):
    device_id: str
    device_token: str


class CloudCommand(BaseModel):
    text: str
    nonce: str


class MemoryQuery(BaseModel):
    query: str = ''
    include_sensitive: bool = False


class ApprovalDecision(BaseModel):
    approval_id: str
    decision: str
    nonce: str


class EmergencyStopBody(BaseModel):
    enabled: bool


class ContinuityResumeBody(BaseModel):
    thread_id: str | None = None
    event_limit: int = Field(default=30, ge=1, le=200)


class ContinuityAppendBody(BaseModel):
    thread_id: str
    kind: str
    payload: dict = Field(default_factory=dict)


class ContinuityContextBody(BaseModel):
    thread_id: str
    patch: dict = Field(default_factory=dict)


class ContinuityHandoffBody(BaseModel):
    thread_id: str
    to_device: str


class ProactiveConsiderBody(BaseModel):
    source: str
    payload: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


class WorkflowCreateBody(BaseModel):
    title: str
    trigger: dict = Field(default_factory=dict)
    steps: list[dict]
    next_run_at: str | None = None
    interval_seconds: int | None = Field(default=None, ge=1)


class WorkflowRunBody(BaseModel):
    workflow_id: str


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

    def auth_device(authorization, device_id):
        if not device_registry or not device_id:
            raise HTTPException(401, 'Device identity required')
        token = (authorization or '').removeprefix('Bearer ').strip()
        if not token or not device_registry.authenticate(device_id, token):
            raise HTTPException(401, 'Unauthorized')
        return device_id

    def require_runtime(name: str):
        value = runtime.get(name) if runtime else None
        if value is None:
            raise HTTPException(503, f'{name} unavailable')
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
        return {
            'ok': True,
            'service': 'personal-ai',
            'version': 'p2',
            'cloud_runtime': cloud is not None,
            'capability_superiority': bool(runtime and runtime.get('benchmark')),
        }

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
        return {'reply': executor.chat(body.text, device_id=device_id)}

    # ------------------------------------------------------------------
    # P2 trusted-device capability API
    # ------------------------------------------------------------------
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
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        return require_runtime('continuity').sync(device_id, limit=max(1, min(int(limit), 500)))

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
        return service.append(body.thread_id, device_id=device_id, kind=body.kind, payload=body.payload)

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
        return {'thread_id': body.thread_id, 'context': service.update_context(body.thread_id, body.patch)}

    @app.post('/continuity/handoff')
    def continuity_handoff(
        body: ContinuityHandoffBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        if not device_registry.is_active(body.to_device):
            raise HTTPException(404, 'Target device is not trusted/active')
        service = require_runtime('continuity')
        active = service.active_for_device(device_id)
        if not active or active['id'] != body.thread_id:
            raise HTTPException(403, 'Source device is not active in the requested continuity thread')
        return service.handoff(body.thread_id, from_device=device_id, to_device=body.to_device)

    @app.post('/proactive/consider')
    def proactive_consider(
        body: ProactiveConsiderBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        device_id = auth_device(authorization, x_device_id)
        context = {**body.context, 'device_id': device_id}
        return require_runtime('proactive').consider(body.source, body.payload, context=context).__dict__

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
        auth_device(authorization, x_device_id)
        return require_runtime('automations').workflows()

    @app.get('/workflows/runs')
    def workflow_runs(
        workflow_id: str | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id)
        return require_runtime('automations').runs(workflow_id, max(1, min(int(limit), 500)))

    @app.post('/workflows/create')
    def workflow_create(
        body: WorkflowCreateBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id)
        workflow_id = require_runtime('automations').create_workflow(
            body.title,
            body.trigger,
            body.steps,
            next_run_at=body.next_run_at,
            interval_seconds=body.interval_seconds,
        )
        return {'workflow_id': workflow_id}

    @app.post('/workflows/run')
    def workflow_run(
        body: WorkflowRunBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id)
        run_id = require_runtime('automations').run_workflow(body.workflow_id, background=True)
        return {'run_id': run_id}

    @app.post('/workflows/pause')
    def workflow_pause(
        body: WorkflowPauseBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id)
        return require_runtime('automations').pause_workflow(body.workflow_id, body.paused)

    @app.post('/workflows/approval')
    def workflow_approval(
        body: WorkflowApprovalBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id)
        engine = require_runtime('automations')
        decision = body.decision.strip().lower()
        if decision == 'approve':
            return engine.approve_run(body.run_id, body.approval_id)
        if decision == 'reject':
            return engine.reject_run(body.run_id, body.approval_id)
        raise HTTPException(400, 'decision must be approve or reject')

    @app.get('/benchmark')
    def benchmark_latest(
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id)
        benchmark = require_runtime('benchmark')
        return {'capabilities': benchmark.latest(), 'tasks': benchmark.task_matrix()}

    @app.post('/benchmark/run')
    def benchmark_run(
        body: BenchmarkRunBody,
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ):
        auth_device(authorization, x_device_id)
        benchmark = require_runtime('benchmark')
        if body.capability.strip().lower() == 'all':
            return benchmark.run_all()
        return benchmark.run(body.capability.strip())

    # ------------------------------------------------------------------
    # Cloud relay API
    # ------------------------------------------------------------------
    @app.post('/cloud/session')
    def cloud_session(body: SessionStart):
        return result(require_cloud().issue_session(body.device_id, body.device_token))

    @app.post('/cloud/session/revoke')
    def cloud_revoke(authorization: str | None = Header(default=None)):
        relay, session = cloud_auth(authorization, 'status:read')
        return result(relay.revoke_session(session.id, session.device_id))

    @app.post('/cloud/command')
    def cloud_command(body: CloudCommand, authorization: str | None = Header(default=None)):
        relay, session = cloud_auth(authorization, 'ai:chat', body.nonce)
        return result(relay.command(session, body.text, body.nonce))

    @app.post('/cloud/memory/search')
    def cloud_memory(body: MemoryQuery, authorization: str | None = Header(default=None)):
        relay, session = cloud_auth(authorization, 'memory:read')
        return result(relay.memory_search(session, body.query, body.include_sensitive))

    @app.get('/cloud/status')
    def cloud_status(authorization: str | None = Header(default=None)):
        relay, session = cloud_auth(authorization, 'status:read')
        return result(relay.status(session))

    @app.get('/cloud/events')
    async def cloud_events(request: Request, authorization: str | None = Header(default=None)):
        relay, session = cloud_auth(authorization, 'status:read')
        events = runtime.get('events') if runtime else None
        if not events:
            raise HTTPException(503, 'Event stream unavailable')
        event_queue = queue.Queue(maxsize=64)

        def push(event):
            safe = {'event': event.get('event')}
            if 'state' in event:
                safe['state'] = event.get('state')
            if event.get('event') == 'emergency.stop':
                safe['enabled'] = bool(event.get('enabled'))
            if event.get('event') == 'approval.required':
                safe['approval_id'] = event.get('approval_id')
                safe['tool'] = event.get('tool')
                safe['expires_at'] = event.get('expires_at')
            if event.get('event') in {'proactive.suggest', 'proactive.notify'}:
                safe['message'] = event.get('message')
                safe['score'] = event.get('score')
            if event.get('event') == 'workflow.approval_required':
                safe['run_id'] = event.get('run_id')
                safe['approval_id'] = event.get('approval_id')
                safe['tool'] = event.get('tool')
            try:
                event_queue.put_nowait(safe)
            except queue.Full:
                pass

        names = (
            'state',
            'emergency.stop',
            'approval.required',
            'approval.approved',
            'approval.rejected',
            'proactive.suggest',
            'proactive.notify',
            'workflow.approval_required',
            'workflow.completed',
            'workflow.failed',
            'continuity.handoff',
        )
        unsubscribers = [events.subscribe(name, push) for name in names]

        async def stream():
            try:
                initial = relay.status(session).payload
                yield f"data: {json.dumps({'event': 'status', **initial}, separators=(',', ':'))}\n\n"
                while not await request.is_disconnected():
                    try:
                        item = await asyncio.to_thread(event_queue.get, True, 15)
                        yield f"data: {json.dumps(item, separators=(',', ':'))}\n\n"
                    except queue.Empty:
                        yield ': keepalive\n\n'
            finally:
                for unsubscribe in unsubscribers:
                    try:
                        unsubscribe()
                    except Exception:
                        pass

        return StreamingResponse(
            stream(),
            media_type='text/event-stream',
            headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'},
        )

    @app.post('/cloud/approval')
    def cloud_approval(body: ApprovalDecision, authorization: str | None = Header(default=None)):
        relay, session = cloud_auth(authorization, 'approval:write', body.nonce)
        return result(relay.approval(session, body.approval_id, body.decision))

    @app.post('/cloud/emergency-stop')
    def cloud_emergency_stop(
        body: EmergencyStopBody,
        x_personal_ai_owner_key: str | None = Header(default=None),
    ):
        return result(require_cloud().set_emergency_stop(x_personal_ai_owner_key or '', body.enabled))

    @app.websocket('/device/ws/{device_id}')
    async def device_ws(ws: WebSocket, device_id: str):
        token = ws.headers.get('authorization', '').removeprefix('Bearer ').strip()
        if not device_registry or not token or not device_registry.authenticate(device_id, token):
            await ws.close(code=4401)
            return
        await ws.accept()
        if device_gateway:
            device_gateway.connect(device_id, ws)
        continuity = runtime.get('continuity') if runtime else None
        if continuity:
            continuity.resume(device_id)
        try:
            while True:
                message = await ws.receive_json()
                if message.get('type') == 'push_registration' and message.get('provider') == 'apns' and message.get('token'):
                    device_registry.set_metadata(device_id, 'push.apns.token', str(message['token']).strip())
                    if message.get('environment'):
                        device_registry.set_metadata(
                            device_id,
                            'push.apns.environment',
                            str(message['environment']).strip().lower(),
                        )
                if message.get('type') == 'continuity_event' and continuity:
                    thread = continuity.active_for_device(device_id)
                    if thread:
                        continuity.append(
                            thread['id'],
                            device_id=device_id,
                            kind=str(message.get('kind', 'device_event')),
                            payload=dict(message.get('payload') or {}),
                        )
                if device_gateway:
                    device_gateway.receive(device_id, message)
                if message.get('type') not in {'result'}:
                    await ws.send_json({'type': 'ack', 'message_id': message.get('message_id')})
        except WebSocketDisconnect:
            pass
        finally:
            if device_gateway:
                device_gateway.disconnect(device_id)

    if runtime:
        from dashboard.api import dashboard_router
        from dashboard.web import dashboard_html

        app.include_router(dashboard_router(runtime, auth_device))

        @app.get('/dashboard-ui', include_in_schema=False)
        def dashboard_ui(request: Request):
            require_loopback(request)
            return dashboard_html()

    return app
