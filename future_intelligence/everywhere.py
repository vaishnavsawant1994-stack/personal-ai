from __future__ import annotations


class PersonalAIEverywhere:
    """P8 device-independent surface registry over one identity/continuity model."""

    SURFACES = {'iphone', 'ipad', 'desktop', 'web', 'watch', 'wearable', 'earbuds', 'car', 'home', 'ar'}

    def __init__(self, *, gate, device_registry=None, continuity=None, continuity_sync=None):
        self.gate = gate
        self.device_registry = device_registry
        self.continuity = continuity
        self.continuity_sync = continuity_sync

    def capabilities(self):
        return sorted(self.SURFACES)

    def resume(self, device_id: str, surface: str):
        surface = surface.strip().lower()
        if surface not in self.SURFACES:
            raise ValueError('unknown surface')
        decision = self.gate.decision('p8')
        if not decision.allowed:
            return {'resumed': False, 'blocked': True, 'reason': decision.reason, 'surface': surface}
        if self.device_registry is not None:
            if not self.device_registry.is_active(device_id):
                return {'resumed': False, 'blocked': True, 'reason': 'trusted active device required', 'surface': surface}
            if hasattr(self.device_registry, 'authorize') and not self.device_registry.authorize(device_id, 'ai:chat'):
                return {'resumed': False, 'blocked': True, 'reason': 'device is not permitted for ai:chat', 'surface': surface}
        if not self.continuity:
            return {'resumed': False, 'blocked': True, 'reason': 'continuity service unavailable', 'surface': surface}
        bundle = self.continuity.resume(device_id)
        thread = bundle['thread']
        context = self.continuity.update_context(thread['id'], {'surface': surface})
        return {'resumed': True, 'surface': surface, 'thread': thread, 'context': context}
