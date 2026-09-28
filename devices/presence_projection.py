from __future__ import annotations

from activities.projection import ActivitiesProjection


class DevicesPresenceProjection:
    """Bounded owner-safe view over canonical device trust and live presence.

    DeviceRegistry remains trust/permission authority. DeviceGateway remains live
    connection evidence. This projection never enrolls, trusts, revokes, or grants.
    """

    MAX_DEVICES = 200
    _SECRET_METADATA = (
        'token', 'secret', 'authorization', 'cookie', 'password', 'credential',
        'private_key', 'api_key', 'refresh', 'bearer',
    )

    def __init__(self, registry, gateway=None):
        self.registry = registry
        self.gateway = gateway

    @classmethod
    def _safe_metadata(cls, metadata):
        output = {}
        for raw_key, raw_value in list((metadata or {}).items())[:50]:
            key = str(raw_key)[:120]
            lowered = key.lower().replace('-', '_')
            if any(marker in lowered for marker in cls._SECRET_METADATA):
                continue
            output[key] = ActivitiesProjection._sanitize(raw_value)
        return output

    def _online_ids(self):
        if self.gateway is None or not hasattr(self.gateway, 'online'):
            return set()
        try:
            return {str(item) for item in self.gateway.online()}
        except Exception:
            return set()

    def _project(self, row, online):
        device_id = str(row.get('id') or '')[:200]
        revoked = bool(row.get('revoked'))
        active = bool(device_id and self.registry.is_active(device_id))
        return {
            'device_id': device_id,
            'display_name': ActivitiesProjection._sanitize(str(row.get('name') or 'Device'))[:120],
            'platform': ActivitiesProjection._sanitize(str(row.get('platform') or 'unknown'))[:80],
            'trust_state': 'revoked' if revoked or not active else 'trusted',
            'presence_state': 'online' if active and device_id in online else ('revoked' if revoked or not active else 'unknown'),
            'connected': bool(active and device_id in online),
            'created_at': row.get('created_at'),
            'last_seen_at': row.get('last_seen_at'),
            'permissions': [str(item)[:120] for item in list(row.get('permissions') or [])[:50]],
            'metadata': self._safe_metadata(row.get('metadata')),
        }

    def list(self):
        online = self._online_ids()
        rows = list(self.registry.list())[:self.MAX_DEVICES]
        return [self._project(row, online) for row in rows]

    def detail(self, device_id):
        wanted = str(device_id or '').strip()
        if not wanted or len(wanted) > 200:
            return None
        return next((item for item in self.list() if item['device_id'] == wanted), None)
