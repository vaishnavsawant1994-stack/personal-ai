from __future__ import annotations
from dataclasses import dataclass, asdict

from models.hybrid import HybridRequest, PrivacyMode


@dataclass(frozen=True)
class ModelTarget:
    id: str
    locality: str
    private: bool
    capabilities: tuple[str, ...]
    available: bool = True
    cost_rank: int = 10


class HybridIntelligenceRouter:
    """P9 compatibility view backed by the canonical GovernedModelRouter.

    The original P9 target registry is retained only for isolated legacy tests
    and migration compatibility. Integrated V1 delegates eligibility to the
    public non-executing canonical router interface.
    """

    def __init__(self, *, gate, canonical_router=None):
        self.gate = gate
        self.canonical_router = canonical_router
        self._targets = {}

    @property
    def authoritative(self) -> bool:
        return self.canonical_router is not None

    def register(self, target: ModelTarget):
        self._targets[target.id] = target

    def targets(self):
        if self.canonical_router is not None:
            output = []
            for provider in self.canonical_router.providers.values():
                output.append({'id': provider.id,'locality': 'local' if provider.private or provider.id == 'self_hosted' else 'external','private': bool(provider.private),'capabilities': tuple(provider.capabilities),'available': bool(provider.configured and self.canonical_router.observability.allowed(provider.id)),'cost_rank': int(provider.cost_rank)})
            return output
        return [asdict(value) for value in self._targets.values()]

    def route(self, *, capability: str, sensitivity: str = 'normal', offline: bool = False):
        decision = self.gate.decision('p9')
        if not decision.allowed:
            return {'routed': False, 'blocked': True, 'reason': decision.reason}
        sensitivity = str(sensitivity).lower().strip()
        canonical_sensitivity = 'internal' if sensitivity == 'normal' else sensitivity
        if self.canonical_router is not None:
            privacy = PrivacyMode.LOCAL_ONLY if offline else PrivacyMode(self.canonical_router.owner_privacy if self.canonical_router.owner_privacy in {mode.value for mode in PrivacyMode} else PrivacyMode.LOCAL_PREFERRED.value)
            request = HybridRequest(capability=capability,sensitivity=canonical_sensitivity,privacy=privacy,allowed_providers=tuple(self.canonical_router.owner_allowed),blocked_providers=tuple(self.canonical_router.disabled))
            candidates = self.canonical_router.eligible_providers(capability, canonical_sensitivity, hybrid_request=request)
            if not candidates:
                return {'routed': False, 'reason': 'no healthy eligible canonical model target'}
            provider = candidates[0]
            return {'routed': True,'target': {'id': provider.id,'locality': 'local' if provider.private or provider.id == 'self_hosted' else 'external','private': bool(provider.private),'capabilities': tuple(provider.capabilities),'available': True,'cost_rank': int(provider.cost_rank)},'policy': {'sensitivity': sensitivity,'offline': bool(offline),'authority': 'GovernedModelRouter','model_output_authority': False}}

        candidates = []
        for target in self._targets.values():
            if not target.available or capability not in target.capabilities: continue
            if offline and target.locality != 'local': continue
            if sensitivity in {'sensitive', 'secret'} and not (target.locality == 'local' or target.private): continue
            candidates.append(target)
        if not candidates: return {'routed': False, 'reason': 'no eligible model target'}
        candidates.sort(key=lambda target: (0 if target.locality == 'local' else 1,0 if target.private else 1,target.cost_rank,target.id))
        return {'routed': True,'target': asdict(candidates[0]),'policy': {'sensitivity': sensitivity, 'offline': offline, 'authority': 'compatibility-only'}}
