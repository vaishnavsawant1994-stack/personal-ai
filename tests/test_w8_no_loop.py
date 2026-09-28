import pytest,requests
from types import SimpleNamespace
from models.governed_router import GovernedModelRouter
from models.router import ModelUnavailable


def test_duplicate_fallback_configuration_cannot_create_route_loop(monkeypatch):
    s=SimpleNamespace(ai_provider='openai',cloud_runtime_enabled=True,hosted_runtime=True,local_ai_explicit=False,local_ai_url='',local_ai_model='',self_hosted_ai_url='',self_hosted_ai_api_key='',self_hosted_ai_model='',model_fallback_providers=('openai','openrouter','openai','openrouter'),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=3,model_local_first=False,allow_external_for_sensitive=True,openrouter_api_key='x',openrouter_model='or',openai_api_key='x',openai_base_url='https://oa.test/v1',openai_model='oa',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='e')
    calls=[]
    def request(method,url,**kwargs):calls.append(url);raise requests.ConnectionError('offline')
    monkeypatch.setattr(requests,'request',request);r=GovernedModelRouter(s)
    with pytest.raises(ModelUnavailable):r.chat('x')
    assert calls==['https://oa.test/v1/chat/completions','https://openrouter.ai/api/v1/chat/completions']
