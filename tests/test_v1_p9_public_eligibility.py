from __future__ import annotations

from types import SimpleNamespace

from future_intelligence.sovereignty import HybridIntelligenceRouter
from models.governed_router import GovernedModelRouter


class Gate:
    def decision(self, _):
        return SimpleNamespace(allowed=True, reason='ok')


class Provider:
    def __init__(self, pid, *, private=True, configured=True):
        self.id=pid; self.private=private; self.configured=configured; self.api_key='x' if not private else ''
        self.capabilities=('chat',); self.cost_rank=1; self.model='test'


class Canonical:
    owner_privacy='local_preferred'; owner_allowed=(); disabled=set()
    def __init__(self):
        self.providers={'local':Provider('local')}; self.observability=SimpleNamespace(allowed=lambda _: True); self.calls=[]
    def eligible_providers(self, capability, sensitivity='internal', *, hybrid_request=None):
        self.calls.append((capability,sensitivity,hybrid_request))
        return (self.providers['local'],)


def test_p9_compatibility_uses_public_canonical_eligibility_interface():
    canonical=Canonical(); router=HybridIntelligenceRouter(gate=Gate(),canonical_router=canonical)
    result=router.route(capability='chat',sensitivity='normal')
    assert result['routed'] is True
    assert result['policy']['authority']=='GovernedModelRouter'
    assert result['policy']['model_output_authority'] is False
    assert canonical.calls and canonical.calls[0][0:2]==('chat','internal')


def test_governed_router_exposes_nonexecuting_public_eligibility():
    assert callable(getattr(GovernedModelRouter,'eligible_providers',None))
