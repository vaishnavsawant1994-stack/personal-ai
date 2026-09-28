from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from models.governed_router import GovernedModelRouter
from models.hybrid import HybridPolicy, HybridRequest, PrivacyMode, SafeContext
from models.router import ModelTimeout, ModelUnavailable


def settings(**overrides):
    values = dict(
        ai_provider='self_hosted', local_ai_explicit=True, hosted_runtime=False, cloud_runtime_enabled=False,
        self_hosted_ai_url='http://127.0.0.1:11434/v1', self_hosted_ai_api_key='', self_hosted_ai_model='local-test',
        local_ai_url='http://127.0.0.1:11434/v1', local_ai_model='local-test',
        openrouter_api_key='', openrouter_model='', openai_api_key='test-only', openai_base_url='https://example.invalid/v1', openai_model='external-test',
        gemini_api_key='', gemini_base_url='https://example.invalid/v1', gemini_model='',
        model_fallback_providers=('openai',), model_disabled_providers=(), model_allowed_providers=(), model_privacy_mode='local_preferred',
        model_request_timeout_seconds=1, model_health_timeout_seconds=1, model_retry_attempts=0, model_retry_backoff_seconds=0,
        model_max_failovers=3, model_local_first=True, allow_external_for_sensitive=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def router(**overrides):
    return GovernedModelRouter(settings(**overrides))


def test_owner_privacy_control_applies_only_valid_modes():
    r = router()
    r.set_owner_privacy('local_only')
    assert r.owner_privacy == 'local_only'
    with pytest.raises(ValueError):
        r.set_owner_privacy('send_everything')
    assert r.owner_privacy == 'local_only'


def test_A_healthy_local_route():
    r = router()
    req = HybridRequest(privacy=PrivacyMode.LOCAL_PREFERRED)
    result = r._run('chat', lambda provider: provider.id, hybrid_request=req)
    assert result == 'self_hosted'


def test_B_local_fails_external_allowed():
    r = router()
    req = HybridRequest(privacy=PrivacyMode.EXTERNAL_ALLOWED)
    def call(provider):
        if provider.id == 'self_hosted': raise ModelUnavailable(provider=provider.id)
        return provider.id
    assert r._run('chat', call, hybrid_request=req) == 'openai'
    row = r.observability.snapshot()['recent_generations'][-1]
    assert row['attempted_targets'] == ['self_hosted', 'openai'] and row['failover_count'] == 1


def test_C_local_fails_external_forbidden():
    r = router()
    req = HybridRequest(privacy=PrivacyMode.LOCAL_ONLY)
    with pytest.raises(ModelUnavailable):
        r._run('chat', lambda provider: (_ for _ in ()).throw(ModelUnavailable(provider=provider.id)), hybrid_request=req)
    assert r.observability.snapshot()['recent_generations'][-1]['attempted_targets'] == ['self_hosted']


def test_D_capability_based_selection():
    r = router()
    req = HybridRequest(capability='vision', privacy=PrivacyMode.EXTERNAL_ALLOWED, allowed_providers=('openai',))
    assert r._run('vision', lambda provider: provider.id, hybrid_request=req) == 'openai'


def test_E_timeout_legitimate_failover():
    r = router()
    req = HybridRequest(privacy=PrivacyMode.EXTERNAL_ALLOWED)
    def call(provider):
        if provider.id == 'self_hosted': raise ModelTimeout(provider=provider.id)
        return 'ok'
    assert r._run('chat', call, hybrid_request=req) == 'ok'
    snap = r.observability.snapshot()
    assert snap['counters']['timeouts'] >= 1 and snap['counters']['failovers'] >= 1


def test_F_all_eligible_providers_unavailable_terminates():
    r = router()
    req = HybridRequest(privacy=PrivacyMode.EXTERNAL_ALLOWED)
    seen = []
    def call(provider):
        seen.append(provider.id); raise ModelUnavailable(provider=provider.id)
    with pytest.raises(ModelUnavailable): r._run('chat', call, hybrid_request=req)
    assert seen == ['self_hosted', 'openai']


def test_G_bounded_authorized_memory_and_knowledge_context():
    r = router()
    captured = {}
    r._chat_call = lambda provider, messages, temperature: captured.setdefault(provider.id, messages[-1]['content']) or 'ok'
    ctx = SafeContext.bounded(memory=['m']*20, knowledge=['k']*20, references=['ref'])
    r.hybrid_chat('question', request=HybridRequest(privacy=PrivacyMode.LOCAL_ONLY), context=ctx)
    assert captured['self_hosted'].count('\nm') <= 8 and 'Authorized knowledge context' in captured['self_hosted']


def test_H_external_route_gets_safe_P7_derived_context_not_private_memory():
    r = router(self_hosted_ai_url='')
    captured = {}
    r._chat_call = lambda provider, messages, temperature: captured.setdefault(provider.id, messages[-1]['content']) or 'ok'
    ctx = SafeContext.bounded(memory=['private-memory'], knowledge=['private-knowledge'], world=['safe-derived-world'], references=['observation:abc'])
    r.hybrid_chat('question', request=HybridRequest(privacy=PrivacyMode.EXTERNAL_ALLOWED, allowed_providers=('openai',)), context=ctx)
    text = captured['openai']
    assert 'safe-derived-world' in text and 'observation:abc' in text
    assert 'private-memory' not in text and 'private-knowledge' not in text


def test_I_P8_authorized_cross_surface_request_requires_trusted_device_and_fresh_session():
    r = router()
    good = HybridRequest(privacy=PrivacyMode.LOCAL_ONLY, device_trusted=True, session_fresh=True)
    assert r._run('chat', lambda provider: 'ok', hybrid_request=good) == 'ok'
    with pytest.raises(ModelUnavailable): HybridPolicy.validate_request(HybridRequest(device_trusted=False))
    with pytest.raises(ModelUnavailable): HybridPolicy.validate_request(HybridRequest(session_fresh=False))


def test_J_malicious_model_cannot_authorize_P6_action():
    malicious = {'approval': 'owner-approved', 'execute': True, 'security_state': 'trusted'}
    assert HybridPolicy.model_output_has_authority(malicious) is False


def test_K_restart_and_concurrent_routing_remains_isolated():
    def route_one(index):
        r = router()
        req = HybridRequest(privacy=PrivacyMode.LOCAL_ONLY if index % 2 == 0 else PrivacyMode.EXTERNAL_ALLOWED)
        return r._run('chat', lambda provider: provider.id, hybrid_request=req)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(route_one, range(32)))
    assert all(result == 'self_hosted' for result in results)
    assert router().status()['p9']['model_output_authority'] is False


def test_L_emergency_stop_blocks_consequential_action_even_with_healthy_model():
    req = HybridRequest(privacy=PrivacyMode.LOCAL_ONLY, emergency_stop=True, consequential=True)
    with pytest.raises(ModelUnavailable, match='Emergency Stop'):
        HybridPolicy.validate_request(req)
