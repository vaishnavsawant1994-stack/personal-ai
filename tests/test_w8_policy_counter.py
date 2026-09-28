import pytest
from types import SimpleNamespace
from models.governed_router import GovernedModelRouter
from models.router import ModelUnavailable

def test_privacy_block_is_observable_without_content(monkeypatch):
    monkeypatch.setattr('requests.request',lambda *a,**k:None)
    s=SimpleNamespace(ai_provider='openai',cloud_runtime_enabled=True,hosted_runtime=True,local_ai_explicit=False,local_ai_url='',local_ai_model='',self_hosted_ai_url='',self_hosted_ai_api_key='',self_hosted_ai_model='',model_fallback_providers=(),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=0,model_local_first=False,allow_external_for_sensitive=False,openrouter_api_key='',openrouter_model='',openai_api_key='x',openai_base_url='https://cloud.test/v1',openai_model='m',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='e')
    r=GovernedModelRouter(s)
    with pytest.raises(ModelUnavailable):r.chat('PRIVATE',sensitivity='sensitive')
    assert r.status()['w8']['counters']['policy_blocked']>=1
    assert 'PRIVATE' not in repr(r.status())
