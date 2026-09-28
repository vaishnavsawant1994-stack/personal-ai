from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Query

from security.request_context import current_trusted_request


def multimodal_world_router(runtime):
    """Trusted owner inspection/control for P7 observations. No ingestion or action authority."""

    router = APIRouter(prefix='/iphone/api/world', tags=['multimodal-world'])
    registry = runtime['device_registry']
    world = runtime['world_understanding']

    def authenticate(device_id: str | None, token: str | None):
        if not device_id or not token or not registry.authenticate(device_id, token):
            raise HTTPException(401, 'This browser is not trusted or its device credential was revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, 'ai:chat'):
            raise HTTPException(403, 'This device is not permitted to inspect Personal AI world context')
        context = current_trusted_request()
        if context is None:
            raise HTTPException(401, 'A trusted browser session is required')
        if context.device_id != device_id:
            raise HTTPException(403, 'Authenticated browser session does not match this device')
        return device_id

    def classifications(device_id: str):
        allowed = {'public', 'normal', 'internal'}
        if hasattr(registry, 'authorize') and registry.authorize(device_id, 'memory:sensitive'):
            allowed.update({'sensitive', 'secret'})
        return allowed

    @router.get('/observations')
    def recent_observations(
        limit: int = Query(default=50, ge=1, le=200),
        modality: str | None = Query(default=None, max_length=40),
        freshness: str | None = Query(default=None, max_length=20),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        if freshness not in {None, 'fresh', 'stale', 'expired', 'unknown'}:
            raise HTTPException(400, 'Unsupported freshness state')
        try:
            rows = world.recent(
                limit=limit,
                modality=modality,
                freshness=freshness,
                allowed_classifications=classifications(device_id),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'observations': [world.safe_projection(row) for row in rows]}

    @router.get('/observations/{observation_id}')
    def observation_detail(
        observation_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        value = world.inspect(observation_id, allowed_classifications=classifications(device_id))
        if value is None:
            raise HTTPException(404, 'Observation not found')
        return value

    @router.get('/observations/{observation_id}/lineage')
    def observation_lineage(
        observation_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        rows = world.lineage(observation_id, allowed_classifications=classifications(device_id))
        if not rows:
            raise HTTPException(404, 'Observation not found')
        return {'lineage': rows}

    @router.delete('/observations/{observation_id}')
    def delete_observation(
        observation_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, 'memory:write'):
            raise HTTPException(403, 'This device is not permitted to delete owner context')
        visible = world.inspect(observation_id, allowed_classifications=classifications(device_id))
        if visible is None:
            raise HTTPException(404, 'Observation not found')
        return {'deleted': world.delete(observation_id, cascade=True), 'observation_id': observation_id}

    @router.get('/capabilities')
    def capabilities(
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        rows = world.capabilities()
        return {
            'capabilities': [
                {
                    'adapter_id': row['adapter_id'],
                    'modality': row['modality'],
                    'state': row['state'],
                    'device_id': row.get('device_id'),
                    'simulation_only': bool(row.get('simulation_only')),
                    'updated_at': row.get('updated_at'),
                }
                for row in rows
            ]
        }

    @router.get('/governed-context')
    def governed_context(
        limit: int = Query(default=20, ge=1, le=100),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token)
        return world.action_context(
            requesting_device_id=device_id,
            allowed_classifications=classifications(device_id),
            limit=limit,
        )

    return router
