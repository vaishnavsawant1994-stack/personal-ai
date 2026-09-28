from types import SimpleNamespace
import pytest
from models.governed_router import GovernedModelRouter
from models.router import ModelUnavailable


def settings(**o):
    d=dict(ai_provider='openrouter',cloud_runtime_enabled=True,hosted_runtime=True,local_ai_explicit=False,local_ai_url='',local_ai_model='',self_hosted_ai_url='',self_hosted_ai_api_key='',self_hosted_ai_model='',model_fallback_providers=('openai',),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=2,model_local_first=False,allow_external_for_sensitive=False,openrouter_api_key='x',openrouter_model='or',openai_api_key='x',openai_base_url='https://cloud.test/v1',openai_model='oa',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='embed');d.update(o);return SimpleNamespace(**d)


def test_capability_mismatch_never_routes_to_incompatible_provider(monkeypatch):
    seen=[]
    class Resp:
        status_code=200;content=b''
        def json(self):return {'data':[{'embedding':[1,2]}]}
    monkeypatch.setattr('requests.request',lambda method,url,**kwargs:(seen.append(url) or Resp()))
    r=GovernedModelRouter(settings())
    assert r.embed('x')==[1.0,2.0]
    assert seen==['https://cloud.test/v1/embeddings']


def test_sensitive_external_only_configuration_fails_closed(monkeypatch):
    called=[];monkeypatch.setattr('requests.request',lambda *a,**k:called.append(a))
    r=GovernedModelRouter(settings())
    with pytest.raises(ModelUnavailable):r.chat('private',sensitivity='secret')
    assert called==[]
