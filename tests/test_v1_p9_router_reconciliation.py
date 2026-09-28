from __future__ import annotations

from types import SimpleNamespace

from future_intelligence.gates import TrustGate
from future_intelligence.sovereignty import HybridIntelligenceRouter


class CanonicalRouter:
    """Minimal test double for the intentional public canonical router contract."""
    owner_privacy = 'local_preferred'
    owner_allowed = ()
    disabled = set()

    def __init__(self):
        self.calls = []
        self.provider = SimpleNamespace(id='self_hosted', private=True, capabilities=('chat',), configured=True, cost_rank=1, latency_rank=1)
        self.providers = {'self_hosted': self.provider}
        self.observability = SimpleNamespace(allowed=lambda provider_id: True)

    def eligible_providers(self, capability, sensitivity, *, hybrid_request=None):
        self.calls.append((capability, sensitivity, hybrid_request))
        return (self.provider,)


def allowed_gate():
    gate = TrustGate(); gate.record_external_proof('p3.permissions', True, source='test-harness'); gate.record_external_proof('p3.reliability', True, source='test-harness'); return gate


def test_p9_compatibility_route_delegates_to_canonical_governed_router():
    canonical = CanonicalRouter(); router = HybridIntelligenceRouter(gate=allowed_gate(), canonical_router=canonical); result = router.route(capability='chat', sensitivity='sensitive')
    assert result['routed'] is True; assert result['policy']['authority'] == 'GovernedModelRouter'; assert result['policy']['model_output_authority'] is False; assert canonical.calls[0][0:2] == ('chat', 'sensitive')


def test_offline_compatibility_request_becomes_local_only_policy():
    canonical = CanonicalRouter(); router = HybridIntelligenceRouter(gate=allowed_gate(), canonical_router=canonical); router.route(capability='chat', offline=True); request = canonical.calls[0][2]; assert request.privacy.value == 'local_only'


def test_p9_gate_still_fails_closed_before_canonical_routing():
    canonical = CanonicalRouter(); router = HybridIntelligenceRouter(gate=TrustGate(), canonical_router=canonical); result = router.route(capability='chat'); assert result['blocked'] is True; assert canonical.calls == []


def test_legacy_registry_remains_compatibility_only_without_canonical_router():
    router = HybridIntelligenceRouter(gate=allowed_gate()); assert router.authoritative is False; assert router.targets() == []
